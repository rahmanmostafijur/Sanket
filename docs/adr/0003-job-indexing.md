# 0003: Indexing jobs for search

Status: accepted

## Context

Search and matching work on canonical `job` rows (ADR 0002). Each job needs a
full-text index and a vector index so that hybrid retrieval (full-text plus
nearest neighbours, fused on rank) can be built on top. Jobs arrive in several
languages (English, Swedish, Bengali), the search text depends on three tables
(the job, its representative posting and that posting's extraction), and
embedding calls cost quota the same way extraction does, so unchanged jobs must
never be sent again.

## Options and decisions

**1. Full-text column: generated or maintained.** A `GENERATED ALWAYS AS`
tsvector can only read columns of its own row. The searchable text needs the
representative posting's description and the extraction's skills, which live in
other tables, so it cannot be generated. A trigger would have to fire on three
tables and re-run on every ingest. Decision: `job.search_vector` is a nullable
column written by the indexing worker from the search document, with
`job.search_hash` recording what it was built from. A tsvector is rewritten
only when the hash differs. The cost is that it can lag behind the source rows
until the worker runs; the hash makes the lag cheap to detect and repair.

**2. Text search configuration.** `simple`: lowercase and split on word
boundaries, no stemming and no stop words. There is no single stemming
configuration that suits English, Swedish and Bengali together, and a wrong
stemmer silently hurts the other languages. Cost: no stemming, so "developers"
does not match "developer", and symbols are dropped ("C++" indexes as "c").
The vector side covers morphology and synonyms. The name is the constant
`TEXT_SEARCH_CONFIG` and is part of `search_hash`, so changing it rebuilds
every vector. Weights: title A; company, skills, seniority, work mode and
employment type B; location C; description excerpt D. Queries use
`websearch_to_tsquery` with a bound parameter (never raises on any input, never
built by string concatenation) and `ts_rank_cd`.

**3. Vector storage.** Table `job_embedding`: `job_id` (cascade delete),
`model_name`, `model_version`, `dimension`, `content_hash`, `embedding
vector(768)`, timestamps, unique on `(job_id, model_name, model_version)`, and
`CHECK (dimension = vector_dims(embedding))`. The column width is fixed at 768
because an index needs a fixed width. `gemini-embedding-001` can return 128 to
3072 dimensions, and 768 is a size its documentation recommends; it keeps the
index to roughly a quarter of the 3072 size. The width is written in the
migration as a literal, in `EMBEDDING_COLUMN_DIMENSIONS`, and in the
`EMBEDDING_DIMENSIONS` setting. The CLI and every indexing entry point check at
startup that the setting equals the constant and the real column width, and
fail before doing any work otherwise. Several `(model_name, model_version)`
rows per job may exist at once, which is what makes a model migration possible
without downtime (below). `model_version` is our own label, bumped when the
embedding text format or the model parameters change; providers do not expose
one.

**4. ANN index: HNSW, not IVFFlat.** HNSW needs no training data and no
rebuild as the table grows, and gives better recall at low latency. IVFFlat
builds faster and smaller, but its quality depends on lists chosen from data
that does not exist yet and degrades as the table changes. Cosine ops
(`vector_cosine_ops`) because stored and query vectors are unit length and the
embedding model is trained for cosine similarity. Build parameters are the
pgvector defaults, written down as `HNSW_M = 16` and `HNSW_EF_CONSTRUCTION =
64` (the migration repeats them); the query-time knob is `hnsw.ef_search`
(`HNSW_EF_SEARCH`, default 100), set per query with `set_config(..., true)`,
which lasts for one transaction and accepts bound parameters. It is raised to
the requested limit when lower. Queries also set `hnsw.iterative_scan =
relaxed_order` (pgvector 0.8 or newer) so the model filter, needed while two
models coexist, does not make the index return too few rows. Caveat: the index
covers all models in the table, and with a model filter the planner may
prefer another plan. During a migration that is only a speed question, not a
correctness one. A partial index per model would remove it if it ever matters.

**5. Hash gates.** The embedding `content_hash` is the sha256 of the embedding
text, model name, model version, dimension and the document format version. A
job is embedded only when no row exists for the active `(model_name,
model_version)` or the stored hash differs. The tsvector has its own
`search_hash`, over the weighted field texts, the text search configuration and
the format version. The tsvector hash is a column on `job` rather than a hash
shared with the embedding because the two depend on different things (the
embedding on the model, the tsvector on the configuration) and are rewritten
independently. The hash is stored with the vector it produced, so a job that
changes while its embedding call is in flight is simply found stale again on
the next run.

**6. What is embedded.** One text per job (format in
`sanket/indexing/document.py`): title, company, location, seniority, work mode,
employment type, minimum years of experience and skills (from the latest
successful extraction of the representative posting), then a description
excerpt with HTML removed, cut at `INDEXING_MAX_DESCRIPTION_CHARS` (default
3000). The excerpt is bounded because the model reads at most 2048 tokens and
Bengali or Swedish text uses more tokens per character than English. Salary is
left out: numbers add noise to semantic similarity and are better as filters.
Jobs without an extraction or description are indexed from title, company and
location. Changing the format changes the hashes, which is intended; bump
`DOCUMENT_FORMAT_VERSION` so the change is explicit.

**7. Embedding provider.** `gemini-embedding-001` through google-genai, behind
an `EmbeddingClient` interface (documents and queries are separate calls so
the provider's task types are used: RETRIEVAL_DOCUMENT and RETRIEVAL_QUERY).
Checked against the Gemini API documentation on 2026-11-17: sizes other than
3072 come back un-normalised, so the client scales every vector to unit length;
`gemini-embedding-2` exists but has no task types (the task is a text prefix)
and may merge several inputs of one call into one multimodal embedding, so it
is refused by the client until a client for it is written and tested. Requests
are paced (`EMBEDDING_REQUESTS_PER_MINUTE`), batched
(`EMBEDDING_BATCH_SIZE`), and retried with backoff on 429, 5xx and network
errors, with the SDK's own retry left off so attempts are not multiplied. The
Gemini Developer API reports no token counts for embeddings, so the summary
has none.

**8. Dead jobs.** A job with `posting_count = 0` is not indexed: the worker
clears its `search_vector` and `search_hash` and deletes all its embeddings
(every model), so search never returns a job nobody can apply to. The job row
stays (ADR 0002). If a posting comes back, the job is indexed again. Full-text
queries also require `posting_count > 0`, so a job that died since the last
worker run is not returned either.

**9. Data use.** The embedding provider is an external service, and on the
Gemini free tier API inputs may be used to improve Google's models. Jobs whose
representative posting comes from a source in `EXTRACTION_EXCLUDED_SOURCES`
(Remote OK, whose terms reserve AI training) are therefore never sent for
embedding. They keep their full-text entry and show up as
`embedding_excluded` in the summary. A consequence: vector search does not
find those jobs, hybrid search still does through full text.

**10. Cost control.** The hash gate means steady state costs nothing; only new
or changed jobs are embedded. A run handles at most `INDEXING_BATCH_LIMIT`
(default 500) jobs that need work, scanning in id order with keyset pagination.
A failed batch leaves its jobs pending without retrying in a loop, a batch the
provider rejects as invalid is retried text by text to isolate the offender,
and the run stops after three failed batches in a row. The default mode is a
dry run that calls nothing.

## Migrating to a new embedding model

1. Set `EMBEDDING_MODEL` and, if it changes, `EMBEDDING_MODEL_VERSION` (or only
   the version for a new document format or parameters). The width must stay
   768, or a new migration and a new column width are needed.
2. Run `python -m sanket.indexing --apply` repeatedly until the summary shows
   nothing left to embed. Rows for the old model keep serving search in the
   meantime because queries name their `(model_name, model_version)`.
3. Switch the serving code to the new version (it reads the same settings).
4. Delete the old rows:
   `DELETE FROM job_embedding WHERE (model_name, model_version) <> (:new_name, :new_version)`.
5. A wider vector needs a new column or table and an index build; that is a
   separate ADR.

## Consequences

- The tsvector and embeddings can lag behind the data until the worker runs.
  The worker is cheap when nothing changed (one scan of the jobs, no external
  call), and `index_jobs(ids)` serves a caller that knows what it touched.
- Finding work scans every job each run: the stored hashes are compared with
  hashes recomputed from the current inputs. At tens of thousands of jobs this
  is seconds. If it ever matters, add a cheap staleness pre-filter.
- The excerpt limits what the description contributes to both indexes.
- `simple` loses stemming. The first labelled query/job pairs should decide
  whether a per-language configuration is worth its complexity.
- The `vector` extension is created by the migration (`CREATE EXTENSION IF NOT
  EXISTS vector`). On Neon the role that runs the migration must be allowed to
  create it; Neon supports pgvector. If it is not, enable it once from the Neon
  console or SQL editor before running the migration. The downgrade leaves the
  extension installed.
- Search quality is untested against real queries. About 100 labelled
  query/job pairs are needed before tuning `ef_search`, weights or the excerpt
  length.
