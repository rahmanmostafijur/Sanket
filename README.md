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
  → [planned] LLM extraction with schema validation
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
pip install -e .

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

The Greenhouse and Lever companies are configured with the
`GREENHOUSE_BOARDS` and `LEVER_COMPANIES` variables.

Considered and not used: The Muse (API shut down), Adzuna (terms need a
licence for aggregate analysis), Arbeitnow (terms forbid public display).