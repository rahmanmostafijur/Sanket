# Deploying Sanket

This describes how the backend is built and run, what each setting does and how
secrets are handled. The order of operations for a release is in
[runbook.md](runbook.md). Nothing here has been deployed: the configuration was
exercised locally with Docker Compose against throwaway containers only.

## Architecture

```
                 GitHub Actions (cron, every 6 h)
                 ingest ─► extraction ─► canonicalise
                          │ DATABASE_URL, GEMINI_API_KEY
                          ▼
 clients ──► reverse proxy / TLS ──► api  ──────────► PostgreSQL + pgvector (Neon)
                                      │  ▲                    ▲
                          rate limits │  │ queue              │
                          and streams ▼  │                    │
                                     Redis ◄──── worker ──────┘
                                                  embeds profiles, matches jobs

 Prometheus ──scrapes──► api /metrics        Grafana ◄── Prometheus
 OpenTelemetry collector ◄── api (optional OTLP traces)
```

| Process | Command (image role) | Purpose | Scaling |
|---|---|---|---|
| api | `api` (`python -m sanket.api`) | HTTP API: search, profiles, matches, probes, metrics | stateless; several are fine with Redis |
| worker | `worker` (`python -m sanket.worker`) | runs queued tasks: embed profiles, match jobs and profiles | several are fine (tasks are idempotent) |
| migrate | `migrate` (`alembic upgrade head`) | applies schema migrations, then exits | exactly one, before api and worker |
| ingest | `ingest` | fetches postings from the sources | one at a time (shares per-source request budgets) |
| other jobs | `extract`, `canonicalise`, `backfill`, `index`, `match`, `dlq` | one-shot operator commands | on demand |

Production ingestion, extraction and canonicalisation currently run in GitHub
Actions (`.github/workflows/ingest.yml`), and production migrations through the
manually triggered `migrate.yml`. The image can run every command, so moving them
onto a host is a change of scheduler, not of code.

## The image

`backend/Dockerfile` is a multi-stage build on a pinned `python:3.12-slim`
(tag and digest). The build stage installs the package into a virtualenv; the
runtime stage copies only that and the Alembic files, runs as the unprivileged
user `sanket` (uid 10001), and contains no compiler, cache or `.env`. Nothing
secret is baked in: every setting is read from the environment at run time.

```
docker build -t sanket-backend backend
docker build --build-arg WITH_OTEL=true -t sanket-backend backend   # with tracing packages
docker run --rm -e DATABASE_URL=... sanket-backend worker
```

The first argument selects the process (`docker/entrypoint.sh`); anything it does
not know runs as a command. The image's `HEALTHCHECK` probes `/healthz` and is
meant for the api role. Inside the image `ENVIRONMENT` defaults to `production`
and the API binds `0.0.0.0:8000`.

CI builds the image on every push (`image` job in `ci.yml`, no push) and
validates the compose file.

## Docker Compose (local and single host)

```
cp .env.example .env            # then edit: see "Secrets" below
docker compose up -d --build api worker
docker compose ps               # api and worker become healthy; migrate exits 0
curl http://127.0.0.1:8000/readyz
```

Services: `db` (pgvector Postgres) and `redis`; `migrate` runs once and the `api`
and `worker` wait for it (`service_completed_successfully`) and for Redis
(`service_healthy`). The api has the image health check and `/readyz` also
verifies the schema (`READYZ_CHECK_MIGRATIONS=true`); the worker pings Redis.
Application containers drop all capabilities, run with a read-only root
filesystem and `no-new-privileges`. Published ports are bound to `127.0.0.1`.

- The compose file rebuilds `DATABASE_URL` (host `db`) and `REDIS_URL` (host
  `redis`) for the containers; all other settings come from `.env`. A database
  password containing `@ : / %` must be percent-encoded.
- Inside the containers `ENVIRONMENT` is `production` unless `.env` sets it, so
  the API refuses to start without authentication. For local work set
  `ENVIRONMENT=development` and `AUTH_DEV_BYPASS=true` (the example file does).
- One-shot jobs: `docker compose --profile jobs run --rm ingest`, or any role,
  for example `docker compose run --rm worker backfill --dry-run`.
- Host ports can be changed with `API_HOST_PORT`, `DB_PORT` and `REDIS_PORT`
  (useful for a second stack on the same machine, together with `-p <name>`).
- Do not run `docker compose down -v` on a stack whose database you care about:
  `-v` deletes the named volumes.

### Observability profile

`docker compose --profile observability up -d` adds Prometheus (`:9090`), Grafana
(`:3000`, login `admin` and `GRAFANA_ADMIN_PASSWORD`, default `admin`; change it)
and an OpenTelemetry collector, all bound to localhost. Prometheus needs the
metrics token:

```
mkdir -p ops/observability/secrets
printf '%s' "$METRICS_TOKEN" > ops/observability/secrets/metrics_token   # same value as in .env
```

The directory is git-ignored. Grafana provisions the Prometheus data source and
the "Sanket overview" dashboard (`ops/observability/grafana/dashboards/`). The
alert rules are in `ops/observability/alerts.yml` (see the runbook for what each
one means) and pass `promtool check rules`. For traces, build the image with
`WITH_OTEL=true` and set `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318`;
the example collector only prints spans, so replace its exporter with a real
backend. Everything under `ops/observability/` is an example to adapt.

## Settings reference

All settings are environment variables, parsed and validated by `sanket.config`
(pydantic-settings). Names are case-insensitive; booleans accept `true`/`false`;
lists are comma separated; an empty value means unset. Secrets are marked **S**:
they are `SecretStr` in code, never logged, and shown as `**********` in `repr`.

**Core**

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` **S** | required | SQLAlchemy URL, `postgresql+psycopg://user:pass@host/db` (Neon: add `?sslmode=require`) |
| `ENVIRONMENT` | `development` | `development`, `test` or `production`; production refuses development shortcuts |
| `REDIS_URL` **S** | unset | task queue, shared rate limits and (with the feed) pub/sub; unset runs without a queue |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / json outside development | see ADR 0010 |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | bind address (the image sets `0.0.0.0`) |

**Authentication** (ADR 0008). The API needs at least one of the first three, or
the development bypass:

| Variable | Default | Meaning |
|---|---|---|
| `AUTH_JWT_SECRET` **S** | unset | HS256 secret, at least 32 characters |
| `AUTH_JWKS_URL` | unset | provider key set, must be `https` outside development |
| `AUTH_API_KEYS` **S** | unset | `owner=key,owner2=key2`, keys at least 24 characters |
| `AUTH_ISSUER`, `AUTH_AUDIENCE` | unset | enforced when set |
| `AUTH_OWNER_CLAIM` | `sub` | claim that becomes the owner id |
| `AUTH_REQUIRED_SCOPE` | unset | tokens without it get 403 |
| `AUTH_LEEWAY_SECONDS` | `30` | clock skew allowed |
| `AUTH_STREAM_TOKEN_SECRET` **S** | unset | enables stream tokens for browsers (at least 32 characters) |
| `AUTH_STREAM_TOKEN_TTL_SECONDS` | `60` | stream token lifetime |
| `AUTH_DEV_BYPASS` | `false` | credential-less requests act as `DEFAULT_OWNER_ID`; only with `ENVIRONMENT=development` |
| `SEARCH_PUBLIC` | `false` | allow `GET /search` without credentials |

**Limits and probes**

| Variable | Default | Meaning |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | ADR 0009 |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | window |
| `RATE_LIMIT_DEFAULT_REQUESTS` / `RATE_LIMIT_SEARCH_REQUESTS` | `120` / `30` | per caller and window |
| `TRUSTED_PROXY_HOPS` | `0` | reverse proxies appending to `X-Forwarded-For`; keep 0 without one |
| `READYZ_TIMEOUT_SECONDS` | `2` | per readiness check |
| `READYZ_CHECK_MIGRATIONS` | `false` | require `alembic_version` at the code's head |
| `METRICS_ENABLED` / `METRICS_TOKEN` **S** | `true` / unset | token required when set; no token means 404 in production |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_ENABLED`, `OTEL_SERVICE_NAME`, `OTEL_SAMPLE_RATIO` | unset / `false` / `sanket-api` / `1.0` | tracing, needs the `otel` extra |

**Ingestion, extraction, indexing, search, queue, matching.** Unchanged by this
phase and documented where they are defined: `.env.example` (every variable with
its default and meaning), [sources.md](sources.md), [indexing.md](indexing.md),
[search.md](search.md) and [matching.md](matching.md). The secrets among them are
`GEMINI_API_KEY`, `HIMALAYAS_API_KEY` and `USAJOBS_API_KEY`. Required in
production by a startup check: `GEMINI_API_KEY` for the worker.

### Startup checks

The API and the worker validate their settings before touching anything and stop
with one message listing every problem (never a value): no authentication
configured, `AUTH_DEV_BYPASS` outside development, secrets that are too short,
malformed `AUTH_API_KEYS`, a non-https JWKS URL, a worker in production without
`GEMINI_API_KEY`. Commands such as `ingest` and `alembic` do not need any of the
API settings and are unaffected.

## Neon (PostgreSQL)

1. Create the project and database. Use the pooled or the direct connection
   string; the application keeps its own pool, and migrations should use the
   **direct** connection (DDL through a transaction pooler can misbehave).
2. Enable pgvector. Migration `c6604cea877e` runs `CREATE EXTENSION IF NOT EXISTS
   vector`, which works on Neon for the project owner role. If your role cannot,
   run `CREATE EXTENSION vector;` once in the Neon SQL editor first, then migrate.
   Check with `SELECT extname FROM pg_extension WHERE extname = 'vector';`.
3. Put the connection string, with `?sslmode=require`, in the `DATABASE_URL`
   secret (GitHub Actions) and in the host's secret store (`api`, `worker`).
4. Neon scales to zero: the first request after idle time is slow. `/readyz`
   allows 2 seconds per check; raise `READYZ_TIMEOUT_SECONDS` if probes flap
   after a wake-up, and keep the readiness probe off the load balancer's
   liveness path.
5. Take a branch or a point-in-time restore point before applying migrations
   (see the runbook).

## Secrets

- Never commit them. `.env` is git-ignored; `.env.example` has placeholders only.
  `ops/observability/secrets/` is git-ignored too.
- Production: store them in the host's secret manager or in GitHub Actions
  secrets, and inject them as environment variables. The image has no secrets and
  the Compose file reads `.env`, which is meant for a single host you control
  (mode 0600, owned by the deploying user).
- Generate random values: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- Logs redact bearer tokens, URL passwords, `key=` and token query parameters,
  but treat that as a safety net: do not log secrets. Stream tokens appear only
  in query strings, which the access log omits.
- Rotation procedures per secret are in the runbook.

## What is not covered

TLS termination and the reverse proxy, DNS, a VPS or other host, backups beyond
Neon's own, log shipping, and the worker's metrics are outside this repository's
configuration. Choose them when the first deployment is planned.
