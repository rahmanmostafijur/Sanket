# Runbook

Operating Sanket: releasing, verifying, rolling back, queue handling, alerts and
secret rotation. Settings and architecture are in [deploy.md](deploy.md).

Every command below that changes data has a dry run first. Run production
commands only with the production `DATABASE_URL` in your environment and read
the output before the next step. Nothing in this repository applies them for you.

## Release: order of operations

Migrations go **before** the code that needs them. They are additive (new tables,
columns, indexes), so the code that is currently deployed keeps working against
the migrated schema; that is what makes the order safe and rollback possible.

### 0. Before you start

- CI is green on the branch to release (tests, lint, types, image build).
- Take a restore point: a Neon branch from the current state, or note the
  point-in-time to restore to. This is the only rollback for data changes.
- Check nothing else is writing: no ingest run in progress (the `prod-db`
  concurrency group of the workflows covers the Actions side).
- Look at what the migrations will do: `alembic history` and the revision files.
- Pre-deploy check of the environment: `ENVIRONMENT=production` and `AUTH_DEV_BYPASS`
  unset or `false` (see the production checklist in [deploy.md](deploy.md)). With the
  bypass on, no process starts in production; the log line is
  `invalid configuration: AUTH_DEV_BYPASS must not be enabled when ENVIRONMENT=production`.

### 1. Apply the migrations to Neon

Pending revisions, in order, with what they add:

| Revision | Adds |
|---|---|
| `e67e00d6f629` | `job` table and `posting.job_id` (canonical jobs) |
| `c6604cea877e` | `job.search_vector` with a GIN index and `job_embedding` (pgvector, HNSW); runs `CREATE EXTENSION IF NOT EXISTS vector` |
| `c8199e1b7ec9` | `profile`, `profile_embedding` and `job_match` tables |

Phase 8 added no migration. If a later phase adds one, it goes at the end of this
list. The head must be a single revision (`alembic heads` shows one line).

Apply with the manually triggered **Migrate production database** workflow
(type `migrate` to confirm), which runs `alembic current`, `alembic upgrade head`
and `alembic current`. From a shell the equivalent is
`DATABASE_URL=<direct url> alembic upgrade head`; in Compose, `docker compose run --rm migrate`.

Verify:

- `alembic current` prints the head revision (`c8199e1b7ec9` or later).
- `SELECT extname FROM pg_extension WHERE extname = 'vector';` returns a row. If
  the migration failed on the extension, enable it in the Neon SQL editor and
  re-run the migration (it is transactional and safe to repeat).
- `\dt` shows `job`, `job_embedding`, `profile`, `profile_embedding`, `job_match`.
- The currently deployed code still works: ingest and any running API answer
  normally.

Rollback: migrations are not rolled back in production. If a migration fails
part-way, Postgres undoes the failed one (DDL is transactional) and you fix the
cause and re-run. If it succeeded but is wrong, restore the Neon branch or
point-in-time taken in step 0, or ship a new corrective migration; do not
`alembic downgrade` against production data. The new tables are empty and unused
by old code, so leaving them in place while rolling the code back is harmless.

### 2. Merge and deploy

Merge the release branch, then deploy the image or the Actions workflows from it.
Start the processes in this order: `api` (it must pass `/readyz`), then `worker`.

Verify:

- `GET /healthz` is 200, `GET /readyz` is 200 with `database: ok` (and `redis: ok`,
  `migrations: ok` when enabled). A 503 names the failing check.
- A request without a credential gets 401 and with a valid token 200 (the startup
  check refuses to boot without authentication, so a running API has some, and the
  settings refuse to load with `AUTH_DEV_BYPASS` in production, so a running one
  has no bypass).
- `GET /metrics` with the token returns `sanket_queue_up 1`.
- The worker log shows `worker starting` and `Listening on <queue>`.
- The next scheduled ingest run succeeds (Actions tab).

Rollback: redeploy the previous image tag (or revert the merge). The migrated
schema stays. Stop the worker first if the old code has no worker; queued tasks
wait in Redis and are not lost. Old code ignores the new tables.

### 3. Backfill normalized fields: dry run, then apply

```
python -m sanket.backfill_normalized --dry-run
python -m sanket.backfill_normalized --apply
```

The dry run only counts. Read the summary (scanned, changed, unknown sources,
failed) and continue only if `failed` is 0 and `changed` is plausible. The apply
step writes only the normalized fields of rows that differ, never `content_hash`,
`raw` or `updated_at`, and is safe to repeat and to interrupt.

Verify: run `--dry-run` again; `changed` is 0.

Rollback: there is nothing to undo for correctness (the values are derived from
`raw`); to undo the writes themselves restore the Neon branch from step 0.

### 4. Extraction

```
python -m sanket.extraction.runner
```

It extracts at most `EXTRACTION_BATCH_LIMIT` pending postings per run with the
configured model (needs `GEMINI_API_KEY`), skips `EXTRACTION_EXCLUDED_SOURCES`,
and stops after repeated provider errors. Watch the cost: a first run over a
large backlog is many provider calls; keep the batch limit and the requests per
minute at the free-tier values until you have checked the quota, and repeat the
command (the scheduled workflow also runs it) until nothing is pending.

Verify: the `extraction summary` line shows `ok` growing and few `provider_error`
or `failed` outcomes.

Rollback: extraction rows are additive and versioned; a bad batch is fixed by a
new schema or prompt version, not by deleting rows. Stop the scheduled step to
stop spending.

### 5. Canonicalise, index and match

```
python -m sanket.canonicalise --dry-run   &&  python -m sanket.canonicalise --apply
python -m sanket.indexing --dry-run       &&  python -m sanket.indexing --apply
python -m sanket.matching embed-profiles --dry-run
python -m sanket.matching rematch --all-jobs --dry-run
```

Each dry run prints what it would do; apply only after reading it. Indexing calls
the embedding provider (`GEMINI_API_KEY`, free-tier pacing) and, with Redis
configured, queues matching for the jobs it embedded; run it repeatedly until the
dry run reports nothing to do. See [indexing.md](indexing.md) and
[matching.md](matching.md).

Verify: `GET /search?q=python` returns results with `degraded: false`; a test
profile moves from `pending` to `ready`; queue gauges return to zero.

Rollback: canonical jobs, index rows and matches are derived data. Rerunning the
commands after a fix recomputes them; the schema is unchanged.

## Queue and dead letters

Tasks run at least once with exponential backoff (ADR 0005). A task that uses up
its attempts, or fails permanently (bad payload, input the provider rejects), is
**dead-lettered** and kept for `QUEUE_DEAD_LETTER_TTL_DAYS`.

```
python -m sanket.queue.dlq list [--limit N]
python -m sanket.queue.dlq requeue <id> ...      # or --all
python -m sanket.queue.dlq purge <id> ...        # or --all
```

Handling:

1. `list` and read the error of each task. A burst with one cause (provider
   outage, expired key, Redis restart) is fixed at the cause first.
2. `requeue` the tasks once the cause is fixed. Requeued tasks get a full set of
   attempts; handlers are idempotent, so requeueing twice is harmless.
3. `purge` what cannot succeed (a deleted profile, a payload from an old format).
4. Work lost from the queue altogether (Redis wiped, a worker killed mid-task)
   is rebuilt from the database: `python -m sanket.matching embed-profiles --apply`
   and `python -m sanket.matching rematch --all-profiles --apply`.

Queue depth that does not drain means no worker is running or it is slower than
the intake: see "The worker is down" below, and check Redis memory.

## The worker is down

The API does not notice a missing worker on its own: `/healthz` and `/readyz` stay green
by design (ADR 0011), queued tasks wait in Redis, and profiles and jobs simply stop being
embedded and matched. A running worker refreshes a heartbeat key in Redis every 10 seconds,
and it expires after 45.

How to see it:

- `sanket_worker_up` on `/metrics` is 0 (1 per live worker), and the `SanketWorkerDown` alert
  fires after 5 minutes if tasks are waiting. `sanket_worker_last_heartbeat_age_seconds`
  shows how stale each live worker is; `sanket_queue_waiting`, `_scheduled` and
  `sanket_queue_oldest_waiting_age_seconds` show what is piling up.
- `docker compose ps worker` shows `unhealthy` (the health check is
  `python -m sanket.worker --check`) or `exited` or restarting. To ask the same question by
  hand: `docker compose exec worker python -m sanket.worker --check` prints why and exits 1.
- `docker compose logs --tail 100 worker`: look for `worker starting`, a configuration
  error (`GEMINI_API_KEY`, `REDIS_URL`) or `cannot reach Redis` at the top, and `Task ... failed`
  lines further down.

What to do:

1. Find the cause in the log. A crash loop with a configuration error is fixed in `.env` or
   the secret store; `cannot reach Redis` is Redis (`docker compose ps redis`).
2. `docker compose up -d worker` (or `restart worker`) starts or replaces it. If it is
   `unhealthy` but its log is quiet, restart it: the heartbeat shows that the process is alive
   and reaches Redis, so a silent hang is a task stuck in a call the timeout cannot break.
3. After it starts, within a minute `sanket_worker_up` is 1 and the container is `healthy`.
   The backlog drains by itself.

Queued work survives the outage. Tasks wait in Redis (append-only persistence keeps them
across a Redis restart), and retries and delayed tasks only move into the queue while a worker
runs, so they resume when one does. A task that was running when the worker was killed is
retried (handlers are idempotent). Only if Redis itself was wiped is work lost; rebuild it
from the database as in Queue and dead letters, step 4. Dead letters do not come back by
themselves: check `python -m sanket.queue.dlq list` after an outage that had provider errors.

## Alerts

Rules are in `ops/observability/alerts.yml`. Look at the logs first: every line of
a request carries its `request_id`, and an error response shows the same id.

| Alert | Meaning | What to do |
|---|---|---|
| `SanketApiDown` | Prometheus cannot scrape the API for 2 minutes | `curl /healthz`; container status and logs; if `/healthz` is fine, check the metrics token (401 on scrape) and the network |
| `SanketApiHighErrorRate` | over 5% of requests are 5xx | find the route in Grafana, then `grep` the logs for `unhandled error` with the request id; usual causes are the database (check `/readyz`), a bad deploy (roll back) |
| `SanketApiSlow` | p95 above 2 s | search slowdown is usually the embedding provider (it falls back to full text after `SEARCH_EMBEDDING_TIMEOUT_SECONDS`) or a cold Neon compute; check provider status and database load |
| `SanketRateLimiting` | steady 429s | find the owner or address in the access log; a client bug or abuse; raise `RATE_LIMIT_*` only if the traffic is legitimate |
| `SanketAuthFailureSpike` | many 401s | an expired signing key or secret after a rotation (see below), a client with a stale token, or guessing; the limiter already throttles per address |
| `SanketQueueUnreadable` | the API cannot read the queue | Redis is down or unreachable; restart it, check `REDIS_URL`; the API keeps serving and rate limits fall back to memory |
| `SanketQueueBacklog` | over 500 tasks waiting | worker down or slow; scale workers or fix the provider; see Queue |
| `SanketQueueStalled` | oldest waiting task over 15 minutes | no worker is consuming; start it and read its log |
| `SanketDeadLetters` | tasks are dead-lettered | handle as in Queue and dead letters |
| `SanketDeadLettersGrowing` | more tasks were dead-lettered in the last 15 minutes | the cause is probably live (provider, key, Redis): read the worker log before requeueing |
| `SanketWorkerDown` | no live worker for 5 minutes while tasks are waiting or scheduled | see "The worker is down" below |
| `SanketWorkerGone` | no live worker for 30 minutes, queue empty or not | same; nothing is embedded or matched until one runs |
| `SanketWorkerFailing` | tasks fail and none completes for 15 minutes | a dependency is down (embedding key, database, provider): read the worker log, fix it, then requeue the dead letters |

`/readyz` flapping after idle time on Neon is a cold start; see deploy.md.

## Rotating secrets

Rotate on a schedule, on staff changes, and immediately after any suspected
exposure (then also review the logs for the period). Order: add the new value,
deploy, confirm, remove the old value.

| Secret | How |
|---|---|
| Neon password / `DATABASE_URL` | reset the role password in Neon, update the `DATABASE_URL` GitHub secret and the host's secret store, restart `api` and `worker`; verify `/readyz` |
| `AUTH_JWT_SECRET` | all tokens signed with the old secret stop working at once: announce it, change the secret in the issuer and the API together, restart the API; clients get 401 and fetch new tokens. For a provider with JWKS, rotate keys at the provider (it publishes both during overlap; the API refreshes its key cache hourly, so restart the API to refresh immediately) |
| `AUTH_API_KEYS` | add the new `owner=newkey` entry next to the old one, deploy, move the caller over, then remove the old entry and deploy again |
| `AUTH_STREAM_TOKEN_SECRET` | change and restart; open streams stay connected, new tokens use the new secret and old ones (one minute) stop verifying |
| `METRICS_TOKEN` | change it in `.env` and in `ops/observability/secrets/metrics_token`, restart `api` and `prometheus` |
| `GEMINI_API_KEY` | create a new key, update the secrets (Actions and the host), revoke the old one; `/search` degrades to full text for the moments the key is missing |
| `HIMALAYAS_API_KEY`, `USAJOBS_API_KEY` | request a new key from the provider and update the GitHub secret |
| Redis password (if used) | update `REDIS_URL` everywhere and restart `api` and `worker`; queued tasks persist with append-only persistence |
| `GRAFANA_ADMIN_PASSWORD` | change it in Grafana's user settings and in `.env` |

After any rotation: check `/readyz`, one authenticated request, the queue gauges
and the log for 401 or connection errors for 15 minutes.
