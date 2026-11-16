# Sanket

Sanket is a job-market intelligence service. It collects job postings
from public job boards on a schedule, normalises them into a common
format, and stores them in PostgreSQL.

Planned: LLM-based extraction of structured fields (skills, seniority,
salary), hybrid search, and a real-time feed that matches new jobs
against user profiles.

## Architecture

```
Sources (RemoteOK, Remotive, We Work Remotely, Jobicy, Himalayas,
         Greenhouse and Lever company boards)
  → Scheduled ingestion (GitHub Actions, every 6 hours)
  → Normalisation into a common posting model
  → Change detection with a content hash
  → PostgreSQL upsert
  → LLM extraction with schema validation
  → Canonical jobs (postings of the same job grouped by fingerprint)
  → Index (full-text tsvector + pgvector embeddings)
  → [planned] Hybrid search (full-text + vector)
  → [planned] Matching and real-time feed
```

### Design decisions

- **One contract for all sources.** Each source adapter converts its
  raw data into a shared `NormalizedPosting` model, so the rest of the
  pipeline does not depend on any single source's format.
- **Content hash for change detection.** A posting is marked as
  changed only when its meaningful fields change. Volatile data, such
  as a per-request tracking token that one source appends to every
  description, is stripped before hashing. The hash is versioned so
  the hashing logic can change safely.
- **Idempotent writes.** Postings are upserted on `(source, source_id)`,
  so re-running ingestion never creates duplicates.
- **Polite, isolated sources.** Every source implements the same small
  interface (`sanket.sources.base.Source`). Requests have explicit
  timeouts, retry with backoff only on network errors, 429 and 5xx, and
  count against a per-source daily request budget stored in the
  database (`source_request`), so the limits hold across CI runs. One
  failing source is logged and the others continue; each run ends with
  one summary line per source.

  ## Tech stack

| Area | Tools |
|---|---|
| Language | Python 3.12 |
| HTTP client | httpx |
| Validation | Pydantic |
| Database | PostgreSQL (Neon in production, Docker locally) |
| ORM and migrations | SQLAlchemy 2.0, Alembic, psycopg 3 |
| Search index | PostgreSQL full-text (tsvector), pgvector (HNSW) |
| Scheduling | GitHub Actions (cron) |
| Testing | pytest |

**Planned:** pgvector, Redis workers, FastAPI, React + TypeScript,
OpenTelemetry, Prometheus, Grafana.

## Status

- [x] **M1: Ingestion.** Scheduled ingestion from two sources into
  PostgreSQL, running unattended every 6 hours.
- [ ] **M2: LLM extraction.** Structured fields extracted from job
  descriptions and validated against a schema. *(in progress)*
- [ ] Hybrid search (full-text + vector)
- [ ] Matching and real-time feed
- [ ] Self-hosted deployment with CI/CD and observability

## Getting started

Requirements: Python 3.12, Docker.

```bash
# 1. Start a local PostgreSQL
docker compose up -d

# 2. Configure environment
cp .env.example .env

# 3. Install the backend
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 4. Create the database tables (local database only)
alembic upgrade head

# 5. Run ingestion once (INGEST_SOURCES in .env leaves out Remotive)
python -m sanket.ingest

# 6. Run the tests
pytest
```

Note: Remotive allows at most four requests per day. The scheduled job
already uses that budget, so do not run Remotive locally, and avoid
running ingestion repeatedly against the live sources.

## Development

CI (`.github/workflows/ci.yml`) runs the same checks on every push and
pull request. To run them locally, from `backend/` with the dev extras
installed (`pip install -e ".[dev]"`):

```bash
ruff check .
ruff format --check .
mypy
pytest -q -rs
```

Database tests need a throwaway local database whose name ends in
`_test`, migrated to head. Create it once in the Docker database, then
point `TEST_DATABASE_URL` at it (same user and password as in `.env`,
host `127.0.0.1`, port 5433). Tests refuse any other host or name.

```bash
docker compose exec db createdb -U "$POSTGRES_USER" sanket_test
DATABASE_URL=<test url> alembic upgrade head
TEST_DATABASE_URL=<test url> pytest -q -rs
```

Without `TEST_DATABASE_URL` the database tests are skipped, and CI fails
on any skipped test. `mypy` is lenient by default; modules listed in the
`[[tool.mypy.overrides]]` section of `backend/pyproject.toml` are checked
strictly, and new modules should be added there.

## LLM extraction (M2)

`python -m sanket.extraction.runner` extracts structured fields from
pending postings and runs in the scheduled workflow after ingestion.

- **Schema.** `sanket/extraction/schema.py` defines `JobExtraction`
  (title, company, seniority, work mode, employment type, ISO country,
  city, up to 30 normalised skills, minimum years of experience and an
  optional salary with an ISO 4217 currency). Unknown values are
  `"unknown"` or null. `SCHEMA_VERSION` and `PROMPT_VERSION` are stored
  with every result.
- **Validation and repair.** The model's JSON is validated; on failure
  the errors are sent back for at most two repairs, after which the
  posting is stored as `failed` with the error. Unvalidated data is
  never stored.
- **Storage.** Results live in `posting_extraction`, one row per
  `(posting, schema_version, prompt_version)`, together with the content
  hash that was extracted, the model, attempts and token usage. A
  posting is pending until its current content hash has an `ok` result
  (or has failed `EXTRACTION_MAX_ATTEMPTS` times).
- **Cost guards.** HTML is stripped and descriptions are truncated
  (`EXTRACTION_MAX_DESCRIPTION_CHARS`), each run is capped
  (`EXTRACTION_BATCH_LIMIT`), and calls are paced to
  `GEMINI_REQUESTS_PER_MINUTE`. A run stops after three provider errors
  in a row.
- **Provider.** Gemini sits behind the small `LlmClient` interface in
  `sanket/extraction/llm.py`, so another provider can be swapped in.
  `extract_posting(posting_id, ...)` handles a single posting and can be
  called from a queue worker unchanged.
- **Data use.** On Gemini's free tier, Google may use API inputs to
  improve its models. Remote OK reserves AI training on its data, so its
  postings are excluded (`EXTRACTION_EXCLUDED_SOURCES`).

## Canonical jobs

The same job often appears in several sources, or is posted again. `job` is
the canonical entity that groups those postings; raw data (`posting`) and
derived data (`posting_extraction`) stay in their own tables. Each posting
gets a deterministic fingerprint (`fp1:` plus a hash of its normalised
company, title and location), and `python -m sanket.canonicalise` links
postings to jobs and keeps each job's count, first and last seen time and
representative posting up to date. It is a dry run unless `--apply` is
passed, is safe to repeat, and also runs at the end of every ingest. The
matching strategy and its limits are in
[docs/adr/0002-job-matching-strategy.md](docs/adr/0002-job-matching-strategy.md);
how to run it and read its summary is in
[docs/canonicalisation.md](docs/canonicalisation.md).

## Search index

Each canonical job gets a weighted full-text vector (`job.search_vector`,
GIN-indexed) and an embedding per model (`job_embedding`, 768-dimensional
pgvector with an HNSW cosine index). `python -m sanket.indexing` builds both
from the job's fields, the extraction of its representative posting and a
bounded description excerpt. It is a dry run unless `--apply` is passed and is
safe to repeat: a content hash means unchanged jobs are never embedded again,
and jobs without postings are removed from the index. Embeddings are behind a
provider-neutral `EmbeddingClient` (Gemini `gemini-embedding-001` for now), and
rows for several model versions can coexist for a model migration. The design is
in [docs/adr/0003-job-indexing.md](docs/adr/0003-job-indexing.md); running it
and reading its summary is in [docs/indexing.md](docs/indexing.md). Search
itself (filters, rank fusion, API) is not built yet.

## Database migrations

The scheduled ingestion workflow does not run migrations. Production
migrations run only through the manual **Migrate production database**
workflow (`.github/workflows/migrate.yml`).

A migration is applied to production **before** the code that depends on
it is merged: run the migrate workflow from the feature branch, check it,
then merge. Migrations must therefore stay compatible with the code
already on `main`.

## Data sources

Job postings come from these public APIs and feeds. Every posting keeps
a link to its original listing, and each source is credited as the
origin of its data.

| Source | Access | Terms that apply |
|---|---|---|
| [Remote OK](https://remoteok.com) | Public API | Link back (do-follow) and name Remote OK as the source; no logo. Its robots.txt reserves AI training (`ai-train=no`): never train or fine-tune on this data. |
| [Remotive](https://remotive.com) | Public API | At most 4 requests a day. Link back and credit Remotive. Do not pass jobs on to other job sites or gate them behind sign-ups. |
| [We Work Remotely](https://weworkremotely.com) | Public RSS feed | Link back to We Work Remotely. |
| [Jobicy](https://jobicy.com) | Public API | Credit Jobicy with a link and keep apply links on Jobicy. At most one pass an hour. Mark closed jobs as unavailable when shown. |
| [Himalayas](https://himalayas.app) | Public API (optional key) | Apply via `applicationLink`, credit Himalayas with a link, at most one run a day. Do not pass jobs on to other boards, aggregators or Google Jobs. Remove jobs once they expire. |
| Greenhouse boards | Public job board API | One request per company per run. Content belongs to each employer; always link back. |
| Lever boards | Public postings API | One request per company per run. Content belongs to each employer; always link back. |
| Ashby boards | Public job board API | One request per company per run. Content belongs to each employer; always link back. |
| [JobTech Sweden](https://jobsearch.api.jobtechdev.se) | Public JobSearch API | Official open data, "free to use and share regardless of purpose" (licence name not read). Bounded pages per run. Contact details are removed before storing. |
| [USAJOBS](https://www.usajobs.gov) | Public API (free key) | Public data may be stored and used commercially. Credit USAJOBS and do not claim OPM endorsement. Skipped without `USAJOBS_API_KEY` and `USAJOBS_USER_AGENT_EMAIL`. |

The Greenhouse, Lever and Ashby companies are configured with the
`GREENHOUSE_BOARDS`, `LEVER_COMPANIES` and `ASHBY_BOARDS` variables.

Which sources are admitted, and why others were not, is set out in
[docs/adr/0001-source-admission-policy.md](docs/adr/0001-source-admission-policy.md)
and [docs/sources.md](docs/sources.md), which also lists the sources that were
considered and not used, such as The Muse, Adzuna and Arbeitnow, with the reason
for each.