# Indexing (operators)

Indexing makes each canonical job searchable: a weighted full-text vector
(`job.search_vector`) and an embedding per model (`job_embedding`). Why it is
built this way is in [adr/0003-job-indexing.md](adr/0003-job-indexing.md); the
exact text that is indexed is documented in
`backend/src/sanket/indexing/document.py`.

## Before the first run

1. Apply migration `c6604cea877e` to the database. It enables the `vector`
   extension (`CREATE EXTENSION IF NOT EXISTS vector`) and adds nullable
   `job.search_vector` and `job.search_hash` plus the `job_embedding` table, so
   the code on `main` keeps working before and after. As with every migration,
   apply it to production with the **Migrate production database** workflow
   from the feature branch **before** the code is merged and deployed.
2. **Neon:** Neon supports pgvector, but the migration role must be allowed to
   create the extension. If the migration fails on `CREATE EXTENSION`, run
   `CREATE EXTENSION IF NOT EXISTS vector;` once in the Neon SQL editor (or
   enable it in the console) and re-run the workflow.
3. Canonicalise first (`python -m sanket.canonicalise --apply`): only jobs with
   postings are indexed. Extraction adds skills and seniority to the text but is
   not required.
4. `GEMINI_API_KEY` is used for embeddings too (only with `--apply`). Check the
   embedding quota shown for the key in Google AI Studio and keep
   `EMBEDDING_REQUESTS_PER_MINUTE` and `EMBEDDING_BATCH_SIZE` under it.

## Running it

From `backend/`:

```bash
python -m sanket.indexing                  # dry run (default): reads only, no API key needed
python -m sanket.indexing --apply          # write
python -m sanket.indexing --apply --limit 100 --batch-size 10
```

Always do a dry run first. The run handles at most `--limit` jobs that need work
(default `INDEXING_BATCH_LIMIT`), oldest id first, so a large backlog is worked
off over several runs. It is safe to repeat and to interrupt: embeddings are
written per batch, and a second run with nothing new makes no embedding call.
It exits non-zero if any job failed or the run stopped early, and those jobs
stay pending for the next run. Other code can call
`sanket.indexing.service.index_jobs(job_ids, cfg, client)` right after it
changes some jobs.

## Reading the summary line

```
indexing mode=apply model=gemini-embedding-001 scanned=620 tsvector_updated=500
  embedded=480 unchanged=100 removed=2 skipped_no_text=0 embedding_excluded=20
  failed=0 stopped_early=false
```

| Field | Meaning |
|---|---|
| `mode` | `dry-run` counts only (an apply run would do the same); `apply` wrote. |
| `scanned` | Jobs examined, up to and including the last one that needed work. |
| `tsvector_updated` | Search vectors written because the hash changed or was missing. |
| `embedded` | Jobs sent to the embedding model and stored. |
| `unchanged` | Jobs that needed nothing. |
| `removed` | Jobs with no postings whose search vector and embeddings were removed. |
| `skipped_no_text` | Jobs with nothing to index (blank title, company, location and description). |
| `embedding_excluded` | Jobs whose representative posting is from a source in `EXTRACTION_EXCLUDED_SOURCES`: full-text only, never sent to the provider. |
| `failed` | Jobs whose write or embedding failed. They stay pending. |
| `stopped_early` | The run stopped after three failed embedding batches in a row (quota, outage, bad key). |

A second run straight after the first shows `tsvector_updated`, `embedded`,
`removed` and `failed` all at 0. No token counts are shown: the Gemini
Developer API does not report usage for embeddings.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `EMBEDDING_MODEL` | `gemini-embedding-001` | Model name; part of the stored key and hash. |
| `EMBEDDING_MODEL_VERSION` | `1` | Our label for model plus settings; bump to embed everything again next to the old vectors. |
| `EMBEDDING_DIMENSIONS` | `768` | Must equal the vector column width; checked at startup. |
| `EMBEDDING_REQUESTS_PER_MINUTE` | `30` | Pacing of embedding requests. |
| `EMBEDDING_BATCH_SIZE` | `20` | Texts per request (at most 100). |
| `INDEXING_BATCH_LIMIT` | `500` | Jobs needing work handled per run. |
| `INDEXING_MAX_DESCRIPTION_CHARS` | `3000` | Description excerpt in the indexed text. Changing it re-embeds changed jobs only. |
| `HNSW_EF_SEARCH` | `100` | Candidates the vector index examines per query (1 to 1000). |

Changing the excerpt length or the document format changes the hashes of every
job whose text moves, so the next run re-embeds them. That is the point of the
hash.

## Changing the embedding model

Follow the steps in ADR 0003, "Migrating to a new embedding model": set the new
model or version, run `--apply` until nothing is left, switch queries, then
delete the old rows. Old and new rows coexist in the meantime. The vector
column is 768 wide; a different width needs a new migration. `gemini-embedding-2`
is refused by the client until a client for it is written.

## Things to know

- A job with no postings has its search entry removed; if its postings come
  back, it is indexed again.
- The tsvector uses the `simple` configuration: no stemming, symbols dropped.
- Retrieval primitives are in `sanket.indexing.queries`:
  `fulltext_candidates(query, limit)` and `vector_candidates(embedding, spec,
  limit)`. They return ranked `(job_id, rank, score)` lists and take optional
  `filters` (`sanket.indexing.filters.SearchFilters`) that are applied inside the
  query. Rank fusion, the service and the API are built on them
  (see [search.md](search.md)).
- To embed a query, build an `EmbeddingClient` with the same
  `EMBEDDING_MODEL`, version and dimensions and call `embed_query`. A query
  vector from another model would be meaningless against these rows.
