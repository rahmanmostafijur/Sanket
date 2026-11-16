# 0005: Task queue library

Status: accepted

## Context

Phase 6 adds work that must not run inside a request or an indexing run: embedding a
saved profile, scoring a changed job against every stored profile, scoring a changed
profile against recent jobs. Later phases add more (notification fan-out, scheduled
sweeps). The planned stack already has Redis on the VPS for the live match feed.

What the queue has to do for us:

- The code base is synchronous (SQLAlchemy Core, psycopg 3, blocking provider
  clients). Handlers are plain functions.
- Retries with exponential backoff, a bounded number of attempts, and a
  dead-letter store that an operator can list, requeue and purge.
- Idempotent enqueue: the same task key while the task is pending is one task
  (an indexing run that sees the same job twice must not queue two matchings).
- Delayed tasks (backoff is one; scheduled sweeps are another).
- Operationally small: one VPS, one Redis, a compose file.
- The developer machine is Windows, the runtime is Linux containers. Tests must
  run on Windows with no server and no network.
- Health: queue depth, age of the oldest task and dead-letter count for `/readyz`.
- Maintained, permissive licence.

Versions below are the ones on PyPI on 2026-11-17.

## Options

**RQ 3.0.0 (BSD-2-Clause, released 2026-10-28).** Synchronous. A worker forks a
"work horse" per job on Linux; `SimpleWorker` runs jobs in the worker process
(works on Windows, used for tests and Windows development). `Retry(max,
interval=[...])` gives per-attempt delays through the scheduled-job registry.
Failed jobs land in `FailedJobRegistry` with their traceback, which can be
listed, requeued and removed. `enqueue(..., job_id=..., unique=True)` raises
`DuplicateJobError` atomically (a Lua script) when the id exists, and
`result_ttl=0` deletes a finished job so the key can be used again. Delayed jobs
through `enqueue_in` and the worker's scheduler. Works with `fakeredis[lua]`
(checked: unique enqueue, retry scheduling and `SimpleWorker` all run against it on
Windows). Warm shutdown on SIGINT/SIGTERM.

**arq 0.28.0 (MIT).** Small and Redis-native, with deferred jobs, job ids for
idempotency and retries, but asyncio-only. Our handlers are blocking, so every
one would run in a thread executor and the DB engine would need an async twin
or constant bridging. No built-in dead-letter store to list and requeue.

**Dramatiq 2.2.1 (LGPL-3.0).** Good middleware (retries with exponential
backoff, time limits) and an in-memory `StubBroker` for tests. Dead-lettered
messages are kept in a Redis structure that has no public list/requeue API and
expires after a week, there is no idempotent-key concept, and the LGPL licence
needs more care than the others. Idempotency, dead-letter handling and health would be our
code reaching into broker internals.

**Celery 5.7.0 (BSD-3-Clause).** The most capable and by far the heaviest:
broker transport layers, result backends, beat, canvas, a large configuration
surface. It has no dead-letter store for the Redis transport (failed tasks are
lost after the last retry unless built by hand) and is the worst fit for Windows
development (the prefork pool needs workarounds). More than this project needs.

**Procrastinate 3.11.0 (MIT), PostgreSQL as the queue.** The best feature match
on paper: `queueing_lock` is exactly idempotent keys, retry strategies with
exponential backoff, scheduled jobs, failed jobs stay in a table, an in-memory
connector for tests, no extra service. Rejected for this project because: it
ships its own schema outside Alembic (a second migration system for the Neon
production database, and `alembic check` would no longer describe the whole
schema); a queue polling or listening on Neon keeps the scale-to-zero database
awake and adds write load to the database that holds the data; the async-first
worker; and Redis is wanted anyway for the pub/sub feed of the next phase, so
it would not remove a service.

**Own implementation on redis-py.** Rejected: at-least-once delivery with a
visibility timeout, worker heartbeats and abandoned-job recovery are exactly
what RQ already does and tests.

## Decision

**RQ 3.0.0 with `fakeredis[lua]` for tests**, behind a small `TaskQueue`
interface in `sanket/queue/` so that handlers, triggers and tests do not import
RQ.

- `TaskQueue.enqueue(task_name, payload, key=None, delay=None) -> EnqueueResult`
  (`ENQUEUED` or `DUPLICATE`), a `TaskRegistry` of `name -> handler`, a dead-letter
  interface (`list`, `requeue`, `purge`) and `health()`.
- One RQ function, `sanket.queue.runner.execute_task(task_name, payload_json)`,
  is the only thing RQ ever calls. It looks the handler up in the registry, parses
  the payload and runs it, so an unknown task or a payload that is not JSON is a
  permanent failure of one job (it goes to the dead-letter store at once,
  without retries) and never crashes the worker.
- Job id = `task_name-key` (the key is hashed when it has characters RQ does not
  allow), `unique=True`, `result_ttl=0`. While a task with that key is queued,
  scheduled for a retry, or running, a second enqueue is a no-op. A finished task
  leaves nothing behind, so the key can be used again. A dead-lettered task keeps
  its id: the same key is not enqueued again until the dead letter is requeued or
  purged, which is deliberate (a poison task must not be retried by every trigger).
- Retries: `QUEUE_MAX_ATTEMPTS` attempts in total, delays
  `QUEUE_BACKOFF_BASE_SECONDS * QUEUE_BACKOFF_FACTOR ** n` capped at
  `QUEUE_BACKOFF_MAX_SECONDS`. Permanent errors skip the retries.
- Dead letters are RQ's failed registry, kept `QUEUE_DEAD_LETTER_TTL_DAYS`. The CLI
  `python -m sanket.queue.dlq list|requeue|purge` lists them (task, key, attempts,
  error, time), requeues by creating a fresh job with a full retry budget, and
  purges.
- Windows: `python -m sanket.worker` uses `SimpleWorker` (no fork) on Windows or
  with `--simple`, and the forking `Worker` otherwise (the compose/Linux runtime).
  Tests use `SimpleWorker` against `fakeredis` and run everywhere.
- Handler functions are idempotent by construction (the matcher upserts), because
  delivery is at-least-once: a worker killed mid-task has the task retried.

## Consequences

- RQ pickles nothing of ours: the only job arguments are two strings (task name,
  JSON payload), so the queue contents are readable and a code change cannot make
  old jobs unloadable.
- The scheduler that moves due retries and delayed tasks runs inside the worker
  (`with_scheduler`), so a worker must be running for backoff and delays to
  elapse. `RqTaskQueue.promote_due(now)` does the same step for tests, with an
  injected clock and no sleeping.
- A job is held in memory in Redis; a Redis loss without persistence loses queued
  work. Compose runs Redis with append-only persistence. Everything the queue
  carries is recoverable from the database (`python -m sanket.matching rematch`
  and `embed-profiles` re-derive the work), so the queue is a latency device, not
  the system of record.
- RQ's work horse forks per job: handlers must open their own database
  connections (the worker disposes the engine pool before forking).
- If we later want to drop Redis from the write path, the interface keeps the
  change inside `sanket/queue/` (a Procrastinate backend is the natural second
  implementation).
