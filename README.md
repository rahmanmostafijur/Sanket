# Sanket

Sanket is a job-market intelligence service. It collects job postings
from public job boards on a schedule, normalises them into a common
format, and stores them in PostgreSQL.

Planned: LLM-based extraction of structured fields (skills, seniority,
salary), hybrid search, and a real-time feed that matches new jobs
against user profiles.

## Architecture

```
Sources (RemoteOK, Remotive)
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

# 4. Create the database tables
alembic upgrade head

# 5. Run ingestion once
python -m sanket.ingest

# 6. Run the tests
pytest
```

Note: Remotive allows at most four requests per day. The scheduled job
already uses that budget, so avoid running ingestion repeatedly against
the live sources.

## Data sources

Job postings come from the public APIs of:

- [RemoteOK](https://remoteok.com)
- [Remotive](https://remotive.com)

Every posting keeps a link to its original listing, and each source is
credited as the origin of its data. Postings are used according to each
source's API terms.