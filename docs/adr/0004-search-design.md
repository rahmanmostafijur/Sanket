# 0004: Search design

Status: accepted

## Context

Jobs are indexed twice (ADR 0003): a weighted full-text vector and an embedding.
Search must answer free-text queries in English, Swedish and Bengali, honour
filters (work mode, seniority, country, source and so on), stay up when the
embedding provider does not, and treat every input as hostile. There are no
labelled queries yet, so the design has to be simple and measurable rather than
tuned.

## Options and decisions

**1. Hybrid retrieval, fused by rank (RRF).** Full-text and vector search each
produce a ranked candidate list. Their scores are not comparable: `ts_rank_cd`
is an unbounded relevance sum that depends on document length and the query,
cosine distance lives in [0, 2] and clusters tightly. Adding, averaging or
normalising them needs per-query calibration that we cannot validate. Reciprocal
Rank Fusion uses only positions: `score(d) = sum over lists of weight / (k +
rank)`. A document that both lists like rises, a document one list loves is not
buried, and neither list can dominate through its scale. Alternatives rejected:
a weighted score sum (needs calibration), taking one list and re-ranking with the
other (loses recall of whichever list is second), and a learned reranker (needs
labelled data, a model and latency we do not have; see out of scope).

**2. `k = 60` and per-list weights, both settings.** 60 is the value from the
original RRF paper and the common default. It flattens the curve so the top
rank is worth only a little more than rank 5. `SEARCH_RRF_K` changes it and
`SEARCH_FULLTEXT_WEIGHT` / `SEARCH_VECTOR_WEIGHT` (default 1.0 each) scale the
lists; a weight of 0 switches a list off, and its provider call is then skipped.
Both stay at their defaults until labelled data (docs/search-evaluation.md)
shows a reason to move them. `rrf_fuse` is a pure function with tests for ties
(best rank, then job id), single-list documents, empty lists, repeated ids and
invalid parameters.

**3. A candidate cap per list.** Each list is limited to `SEARCH_CANDIDATES`
(default 100). That bounds query cost, keeps RRF meaningful (deep ranks add
almost nothing) and bounds the page depth.

**4. Pre-filter, not post-filter.** Filters are conditions inside both candidate
queries, so the lists are the best matches among jobs that pass. Filtering the
top 100 afterwards would return few or no results for a restrictive filter even
when matching jobs exist. For the vector query this relies on the iterative
index scan introduced in ADR 0003 (`hnsw.iterative_scan = relaxed_order`):
the HNSW scan keeps producing neighbours until enough rows pass the filter.
Observed on a local 20,000-job dataset, `EXPLAIN ANALYZE` showed the planner
using the HNSW index with the job and extraction filters applied inside the scan
loop. Limit: pgvector stops after `hnsw.max_scan_tuples` (default 20,000)
examined rows, so for a filter that matches well under 0.5% of the index, the
vector list can come back shorter than `SEARCH_CANDIDATES`. The full-text list is
not affected, and the response is still correct, only possibly shallower. The
iterative scan can return rows slightly out of distance order, so the candidates
are put in exact order before they are ranked.

**5. Where filter values come from.** From the canonical `job` row (company,
location, first seen, whether it has postings) and from the newest successful
extraction of the job's representative posting, a JSONB document (work mode,
seniority, employment type, country, skills). A job without a successful
extraction never matches a filter on those fields; that is a visible gap rather
than a guess. `source` matches a job if any of its postings comes from the
source. `posted_after` uses the representative posting's `published_at` and falls
back to `first_seen_at` when the source gave no date. `skills` is all-must-match
(a skill filter is a requirement; ORing skills widens results, which the text
query already does), compared case-insensitively. Repeated values within the
other fields are ORed.
**Salary is not a filter.** The extraction carries amount, currency and an
optional period but nothing is converted to one currency or one period, and the
period is often null. A minimum-salary filter would compare unlike numbers and
silently drop jobs. The amounts are returned with each result instead; a
filter needs normalised salary fields first (a later extraction change).

**6. No new index or migration.** The JSONB fields are read through a lateral
subquery on the unique `(posting_id, ...)` index of `posting_extraction`, and the
other conditions are cheap column or primary-key lookups. On the local 20,000-job
dataset a filtered query took roughly 40 to 220 ms, an unfiltered one about 80 ms
(Docker on a laptop, warm cache). The slowest case was a very selective date
filter, where the scan walks many index rows. That is acceptable at this size, so
no expression or GIN index is added. If filters become hot at larger sizes the
first step is a GIN index on the extraction `data` (or a normalised skills
array), added with its own ADR and EXPLAIN evidence. The filtered vector query
is not asserted by an EXPLAIN-based test, because the plan depends on table
statistics.

**7. Degraded mode.** The query embedding comes from the same
`EmbeddingClient` as indexing. If it is disabled (no key) or fails for any
reason, search answers from full text only and the response says so
(`degraded: true`, `degraded_reason` of `embeddings_disabled` or
`embedding_failed`); it never returns a 500 for that. Any exception from the
provider is caught and logged, because a provider fault must not turn into an
outage of search. Database errors are not caught. Search waits at most
`SEARCH_EMBEDDING_TIMEOUT_SECONDS` (default 5) and tries twice, instead of the
indexer's patient schedule. Query embeddings are cached in process by `(model,
version, dimensions, normalised query)` with a bounded LRU
(`SEARCH_QUERY_CACHE_SIZE`, default 1000), which also makes paging through one
query cost one embedding call. Failures are not cached. A per-user budget for
embedding spend belongs to the rate limiting of the later API phase.

**8. Pagination.** Offset and limit apply to the fused list, which holds at
most `SEARCH_CANDIDATES` results. The response gives `total_candidates` (the
size of that list) and `has_more`. An offset at or past the end returns an
empty page, so deep paging beyond the cap yields nothing; this is deliberate.
Cursor paging was rejected: results are a ranking recomputed per request, there
is no stable cursor over a fused ranking, and nobody pages 100 deep through
search results. `limit` is at most 50 and `offset` at most 1000. The ranking is
deterministic for a given index state, so adjacent pages do not overlap.

**9. Input is untrusted.** Every value reaches the database as a bound
parameter. The query goes through `websearch_to_tsquery`, which accepts any text
and never raises; location uses `icontains(..., autoescape=True)`, so `%` and `_`
match themselves; a NUL character, which PostgreSQL text cannot hold, is
rejected with 422 before it reaches the driver. Request models forbid unknown
parameters, trim text, bound its length and the number of repeated values.

**10. Results link back and credit their source.** Every item carries `source`,
its display name, the canonical `url` of the representative posting, every source
that lists the job, and an `attribution` line where the provider's terms ask for
credit (Remote OK, Remotive, We Work Remotely, Jobicy, Himalayas, USAJOBS,
JobTech; docs/sources.md). Dead jobs (no postings) never appear. A client must
show the credit and link back to `url`.

**11. Structure.** `sanket.search` holds the pure fusion and metrics, the
retrieval and service layers and the evaluation harness; `sanket.api` holds the
FastAPI app factory (everything injected: database engine, embedding client,
settings), schemas and the router. The factory accepts global `dependencies`,
which is where authentication goes later; there is none in this phase, so the
server binds to `127.0.0.1` by default.

## Out of scope, deliberately

- **Reranking** with a cross-encoder or an LLM: needs labelled data to prove it
  helps and adds latency and cost.
- **Query understanding** (spelling correction, synonym expansion, extracting
  filters from the sentence, language detection): the vector side covers some
  of it; measure first.
- **Personalisation** and matching against profiles (the matcher milestone).
- **Stemming** and per-language text configurations (ADR 0003 records why).
- **Authentication, rate limiting, standard error bodies, health checks**: the
  API hardening phase.

## Consequences

- Search quality is unmeasured against real queries. The evaluation harness
  (docs/search-evaluation.md) exists so tuning of `k`, the weights, `ef_search`
  and the document text can be judged; about 100 labelled query and job pairs
  are needed before any tuning, and none of it has been tuned.
- Filters that need an extraction exclude jobs that have none or whose
  extraction failed.
- Remote OK jobs have no embedding (ADR 0003), so they are found by full text
  only and are shown as `matched_by: "text"`.
- Each request makes two database queries (plus one for the page details) and,
  on a cache miss, one provider call.
- The fused list is capped; users cannot page past `SEARCH_CANDIDATES`.
