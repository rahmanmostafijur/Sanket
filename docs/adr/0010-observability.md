# 0010: Logging, errors, probes, metrics and tracing

Status: accepted

## Context

The API and the worker are about to run unattended in containers. Operators need
to find out that something is wrong without reading code, trace one request
through the logs, hand a stable error to a client, and let an orchestrator know
when to restart or hold traffic. Secrets (bearer tokens, the database and Redis
passwords, the embedding key) must never end up in any of it.

## Decisions

**1. Logging.** One handler on the root logger, installed by
`configure_logging()` in every entry point (API, worker, ingest, indexing,
matching, extraction, canonicalise, backfill, DLQ, evaluation) in place of
`logging.basicConfig`. Format is JSON lines (`time`, `level`, `logger`,
`message`, `request_id`, extra fields, `exception`, and `trace_id` when tracing
is active) or the old text line; `LOG_FORMAT` chooses, and unset means text in
development and JSON elsewhere. `LOG_LEVEL` sets the level. Every line passes
through `redact`, which masks bearer tokens, `user:password@` in URLs, `key=`
and token query parameters, and `password|secret|token|api_key|authorization`
assignments, in messages and tracebacks; extra fields with such names are
masked by name. HTTP client libraries that log full URLs are held at WARNING.
Redaction is a safety net on top of not logging credentials in the first place.

**2. Request ids and the access log.** A pure ASGI middleware accepts an
`X-Request-ID` of 8 to 128 safe characters or makes one, stores it in a context
variable (so every log line of the request carries it) and returns it in the
response. It writes one access line per request (method, path, status,
duration). The query string is never logged, because stream tokens (ADR 0008)
travel in it. Health and metrics requests log at DEBUG. uvicorn's own access log
and logging config are switched off so there is one stream, in one format.

**3. One error envelope.**

```json
{"error": {"code": "not_found", "message": "profile not found", "request_id": "...",
           "details": [{"loc": ["body", "name"], "msg": "...", "type": "..."}]}}
```

`details` appears for validation errors only and never contains the submitted
values. HTTP errors, validation errors, rate limits (429) and unhandled
exceptions all use it. The middleware catches an exception that escaped the
app, logs it with its traceback, and answers a generic 500 (`internal_error`),
so the response still carries the request id and no internals leak. Success
bodies are unchanged. Probes and `/metrics` answer their own shapes, because
orchestrators read their status codes.

**4. Probes.** `/healthz` is liveness: it touches nothing and answers 200 while
the process serves requests. `/readyz` is readiness: the database (`SELECT 1`),
Redis when `REDIS_URL` is set (ping) and, with `READYZ_CHECK_MIGRATIONS=true`,
that `alembic_version` equals the single head the code ships. Checks run in
parallel threads under `READYZ_TIMEOUT_SECONDS` (2), and the answer is 200 or
503 with the name and state (`ok`, `failed`, `timeout`) of each check and no
error text. The migration check is off by default because a rollback runs old
code against a newer schema; the compose file turns it on, since migrations run
as a one-shot job before the API starts. Both probes are public and not rate
limited.

**5. Metrics.** Prometheus text on `GET /metrics`, from a registry owned by the
app: `sanket_http_requests_total{method,route,status}` and
`sanket_http_request_duration_seconds{method,route}` (route is the template, and
unmatched paths share one label, so cardinality is bounded by the route table);
`sanket_queue_up`, `sanket_queue_waiting`, `sanket_queue_scheduled`,
`sanket_queue_running`, `sanket_queue_dead_letters` and
`sanket_queue_oldest_waiting_age_seconds` read from the task queue at scrape
time (cached 10 seconds; `queue_up 0` when Redis cannot be read). Access: with
`METRICS_TOKEN` the endpoint requires it as a bearer token; without one it is
open in development and test and answers 404 in production, so forgetting the
token hides the data instead of exposing it. A user credential is not a scrape
credential. Not included: per-match and per-notification counters (counting
`job_match` rows at every scrape is not cheap; they are derivable from the
database and the logs), and worker-process metrics (the worker is not an HTTP
server; its queue effects show in the queue gauges and its logs).

**6. Tracing.** OpenTelemetry is an optional extra (`pip install "sanket[otel]"`),
imported lazily, and off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set (or
`OTEL_ENABLED=true` for the exporter's default endpoint). When on, the FastAPI
app and the SQLAlchemy engine are instrumented and spans go over OTLP/HTTP, with
a parent-based ratio sampler (`OTEL_SAMPLE_RATIO`). Health, readiness and metrics
requests are not traced. A missing package or a broken exporter is logged and the
API runs untraced; tracing never prevents startup. The worker is not traced.

**7. Alerting and dashboards** are shipped as files under `ops/observability/`
(Prometheus scrape config and alert rules, a Grafana dashboard, an OpenTelemetry
collector config); they are examples to adapt, and nothing is deployed from here.

## Consequences

- Logs are one JSON object per line on stderr; shipping them is the platform's job.
- Metrics are per API process; with several processes Prometheus scrapes each
  target and aggregates by `sum`.
- Redaction is pattern based and cannot catch a secret with no recognisable
  shape written as bare text; keep not logging values.
- Checked against the real packages (opentelemetry 1.x, FastAPI instrumentation): HTTP
  spans work. The SQLAlchemy instrumentation package did not yet support SQLAlchemy 2.1
  when this was written (it logs an error and instruments nothing), so database spans
  appear only once a release that supports it is installed; nothing else is affected.
- Request ids are not propagated into queued tasks; correlating a profile save
  with its embedding task is done by the profile id in the logs.

## Amendment, 2026-11-17: worker metrics

Decision 5 left worker-process metrics out. [ADR 0011](0011-worker-visibility.md) adds them
without an HTTP server in the worker: the worker writes a heartbeat key and task counters in
Redis, and the API's `/metrics` exports `sanket_worker_up`,
`sanket_worker_last_heartbeat_age_seconds` and `sanket_worker_jobs_*_total` at scrape time.
`/healthz` and `/readyz` still ignore the worker. The worker has no tracing.
