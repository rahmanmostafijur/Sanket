# Search (operators and API users)

Hybrid job search over the index from [indexing.md](indexing.md). Why it is built
this way is in [adr/0004-search-design.md](adr/0004-search-design.md); how to
measure it is in [search-evaluation.md](search-evaluation.md).

## Running the API

From `backend/`:

```bash
python -m sanket.api        # serves on API_HOST:API_PORT, default 127.0.0.1:8000
```

It binds to loopback unless you change `API_HOST`. Search needs no credential (see
[adr/0008-authentication.md](adr/0008-authentication.md)), and is rate limited ([adr/0009-rate-limiting.md](adr/0009-rate-limiting.md)). Errors use the
envelope `{"error": {"code", "message", "request_id", "details"}}`. Interactive documentation is at `/docs` and the
OpenAPI document at `/openapi.json`. The index must exist first (`python -m
sanket.indexing --apply`), and the server checks at startup that
`EMBEDDING_DIMENSIONS` matches the vector column.

Queries are embedded with the same model as the index (`EMBEDDING_MODEL`,
`EMBEDDING_MODEL_VERSION`, `GEMINI_API_KEY`). Without a key the server still
starts and answers from full text only (`degraded: true`). The query text is sent
to the embedding provider; on Gemini's free tier, Google may use API inputs to
improve its models.

## `GET /search`

| Parameter | Meaning |
|---|---|
| `q` | Required. 1 to 200 characters after trimming. Understands `"phrases"`, `or` and a leading `-` to exclude a word. |
| `limit` | Page size, default 20, at most 50. |
| `offset` | Results to skip, default 0, at most 1000. |
| `work_mode`, `seniority`, `employment_type` | Values from the extraction schema (`remote`/`hybrid`/`onsite`/`unknown`, `intern`/`junior`/`mid`/`senior`/`lead`/`unknown`, `full_time`/`part_time`/`contract`/`internship`/`unknown`). Repeat for OR. |
| `country` | ISO 3166-1 alpha-2 code of the job country (from the extraction), case-insensitive. Repeat for OR. |
| `source` | Source identifier such as `remoteok`; matches a job if any of its postings is from it. Repeat for OR. |
| `company` | Exact company name, case-insensitive. |
| `location` | Text contained in the location, case-insensitive; `%` and `_` match themselves. |
| `posted_after` | Date or date-time. A date means 00:00 UTC, a time without a zone is UTC. Uses the posting's date, or when we first saw the job if the source gave none. |
| `skills` | Repeat; the job must list every one of them (case-insensitive). |

There is no salary filter: extracted salaries are not normalised to one currency
and period, so they could not be compared fairly (ADR 0004). The amounts are in
each result.

Unknown parameters, bad values and a NUL character are rejected with `422` (the problems are in `error.details`).

Example:

```
GET /search?q=python%20backend&work_mode=remote&work_mode=hybrid&skills=postgresql&limit=10
```

### Response

```json
{
  "query": "python backend", "limit": 10, "offset": 0,
  "total_candidates": 37, "has_more": true,
  "degraded": false, "degraded_reason": null,
  "items": [{
    "job_id": 42, "title": "Senior Backend Engineer", "company": "Acme",
    "location": "Berlin, Germany",
    "source": "remoteok", "source_name": "Remote OK",
    "url": "https://remoteok.com/remote-jobs/123",
    "attribution": "Job listing from Remote OK",
    "sources": [{"source": "remoteok", "name": "Remote OK"}],
    "published_at": "2026-11-01T09:00:00Z", "first_seen_at": "2026-11-01T10:00:00Z",
    "salary_text": null,
    "extracted": {"work_mode": "remote", "seniority": "senior", "employment_type": "full_time",
                  "country": "DE", "city": "Berlin", "skills": ["Python", "PostgreSQL"],
                  "min_years_experience": 5, "salary": null},
    "score": 0.0325, "matched_by": "both"
  }]
}
```

- `score` is the fused rank score. It orders results within one response and is
  not comparable between queries.
- `matched_by` is `text`, `vector` or `both`: which candidate lists contained the job.
- `total_candidates` is the size of the fused list (at most `SEARCH_CANDIDATES`).
  `has_more` is true when a later page has results. An offset at or past
  `total_candidates` returns an empty page: results beyond the candidate cap
  cannot be paged to.
- `degraded` is true when only full-text results were used because the query
  could not be embedded; `degraded_reason` is `embeddings_disabled` or
  `embedding_failed`.
- `extracted` is null for a job with no successful extraction. Such jobs match
  text and vector search but never an extraction-based filter.
- Jobs with no postings never appear.

### Showing results (source terms)

Show `attribution` wherever it is not null and link to `url` (do-follow for
Remote OK, no logo). Terms per source are in [sources.md](sources.md). Do not use
Remotive jobs to collect sign-ups. Remote OK jobs have no embedding, so they are
only ever `matched_by: "text"`.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | Where `python -m sanket.api` listens. |
| `SEARCH_CANDIDATES` | `100` | Candidates per ranked list; also the deepest reachable result (1 to 1000). |
| `SEARCH_RRF_K` | `60` | RRF constant. |
| `SEARCH_FULLTEXT_WEIGHT` / `SEARCH_VECTOR_WEIGHT` | `1.0` / `1.0` | Per-list weights in the fusion; 0 switches a list off. |
| `SEARCH_QUERY_CACHE_SIZE` | `1000` | Query embeddings kept in process; 0 disables the cache. |
| `SEARCH_EMBEDDING_TIMEOUT_SECONDS` | `5` | How long to wait for the query embedding before falling back to full text. |
| `HNSW_EF_SEARCH` | `100` | Vector index candidates examined per query (see indexing.md). |

Do not change the weights, `k` or `ef_search` without labelled data: see
[search-evaluation.md](search-evaluation.md).

## Things to know

- With a very selective filter (well under 0.5% of jobs), the vector list can
  be shorter than `SEARCH_CANDIDATES`, because pgvector stops its iterative scan
  after `hnsw.max_scan_tuples` (20,000 by default) rows. The text list and the
  correctness of the result are unaffected.
- The query embedding cache is per process.
- No migration was needed for search; the filters read the existing tables.
