# 0011: Worker visibility

Status: accepted

## Context

The worker embeds profiles and matches jobs from the Redis queue. It is a separate process with
no HTTP server, and until now a dead worker was silent: the API kept answering, `/readyz` stayed
green, queued tasks just waited, and the compose health check only pinged Redis, so a wedged
worker looked healthy. ADR 0010 left worker metrics out for the same reason (the API cannot
scrape another process's memory).

What operators need:

- Know that a worker is gone, quickly, without reading logs: a metric, an alert, a container
  that turns `unhealthy`.
- Know what the workers did: tasks processed, failed and retried, and the queue depth.
- Keep the API's liveness and readiness independent of the worker, and keep the heartbeat
  working when the API is down.
- Stay small: one VPS, one Redis, one image, `prometheus_client` and the JSON logs already in
  use, tests on fakeredis with no network.

## Options

**Liveness signal**

1. **RQ's own worker registry.** RQ keeps `rq:worker:<name>` with a `last_heartbeat` and a TTL
   (420 seconds by default) and refreshes it in its dequeue loop and, for a forking worker,
   while the child runs. A `SimpleWorker` (Windows, and when asked) blocks in the task and does
   not refresh it, the default detection time is seven minutes, and reading it ties us to
   RQ's internal key layout and to its versions. Rejected as the primary signal.
2. **A heartbeat thread of our own** writing `sanket:worker:heartbeat:<name>` with a TTL.
   Independent of RQ and of the worker class, beats while a task runs and while the worker is
   idle, and has an interval and TTL we choose. It proves the process is alive and can reach
   Redis; it does not prove a task is progressing. Chosen.
3. **A health/metrics HTTP server inside the worker.** Works without Redis for the check, but
   adds a listener, a port and a scrape target to a process that has none, and a wedged
   process answers from its server thread just as the heartbeat thread does. Rejected.

**Worker metrics**

1. **Counters in Redis, read by the API at scrape time.** The task runner adds to a hash on
   each outcome. Same pattern as the queue gauges, no new port, no new scrape job, works for
   several workers and across restarts.
2. **Prometheus multiprocess mode** (files in a shared directory). Needs a volume shared by
   worker and API and breaks when they run on different hosts. Rejected.
3. **A metrics endpoint in the worker.** See option 3 above; also a second scrape target.

## Decision

**1. Heartbeat.** While `python -m sanket.worker` runs, a daemon thread writes
`sanket:worker:heartbeat:<worker name>` = unix time with a TTL, once at start and then every
`WORKER_HEARTBEAT_INTERVAL_SECONDS` (default 10), expiring after
`WORKER_HEARTBEAT_TTL_SECONDS` (default 45; settings validation requires at least three
intervals, so one late beat does not expire it). The worker name is `WORKER_NAME`, else the host
name, which is the container id in Docker, so a health check in the container finds the key
without knowing a pid; two workers must not share a name. On a clean exit (end of a burst,
SIGTERM, Ctrl+C, an error) the worker deletes its key; if the process is killed the key expires.
The thread has a Redis client of its own, because a forking RQ worker forks a child per task
and must not inherit a connection pool another thread may hold. A failed beat is logged and the
thread carries on. The beat means "the process is alive and reaches Redis". A task that hangs
inside the worker is bounded by the task timeout (`QUEUE_TASK_TIMEOUT_SECONDS`, which RQ applies
to each task), and a worker that is alive but not consuming shows as a growing queue and
`sanket_queue_oldest_waiting_age_seconds`.

**2. Health check.** `python -m sanket.worker --check` reads this worker's key and exits 0 only
if it exists and is at most the TTL old, else 1, printing one line (never the Redis URL). It
imports no queue or matching code, so it is cheap enough to run every 15 seconds. The compose
worker service uses it as its health check with a 30 second start period; a wedged worker or
one cut off from Redis becomes `unhealthy`. Compose does not restart on `unhealthy`, so the
check is a signal for `docker compose ps` and for whatever supervises the host.

**3. Metrics on the API.** At scrape time (readings cached for 10 seconds, a failed read
included, so an unreachable Redis costs one timeout per interval) the API's `/metrics` adds:

- `sanket_worker_up`: workers whose heartbeat key exists and is at most the TTL old.
- `sanket_worker_last_heartbeat_age_seconds{worker}`: age of each live worker's last beat.
- `sanket_worker_jobs_processed_total`, `sanket_worker_jobs_failed_total` and
  `sanket_worker_jobs_retried_total`, labelled `queue` and `task`.

These are only exported when the queue is Redis-backed and readable; otherwise they are left out
(`sanket_queue_up` is 0 when Redis cannot be read) and the API carries on. Queue depth is the
existing `sanket_queue_waiting` (with `_scheduled`, `_running`, `_oldest_waiting_age_seconds`
and `_dead_letters`); no second depth gauge is added.

**4. Counters.** `sanket.queue.runner.execute_task`, the one function RQ runs, adds one to the
field `<outcome>:<task>` of the hash `sanket:worker:stats:<queue>`: `processed` when the handler
returns, `retried` when it fails and a retry is scheduled, `failed` when it fails for good (a
permanent error, or the last attempt) and the task is dead-lettered. The task label is a
registered task name or `unknown`, so the number of fields is bounded by tasks times three
outcomes, and label cardinality stays low. A failure to count is logged and never fails the
task. Counters are cumulative and survive worker restarts; a wiped Redis resets them, which
Prometheus handles as a counter reset. A task lost to a hard kill is not counted until its
retry runs.

**5. Alerts and dashboard.** `ops/observability/alerts.yml` gets `SanketWorkerDown` (no live
worker for 5 minutes while tasks are waiting or scheduled; pages), `SanketWorkerGone` (no live
worker for 30 minutes whatever the queue holds), `SanketWorkerFailing` (tasks fail and none
completes for 15 minutes) and `SanketDeadLettersGrowing` next to the existing
`SanketDeadLetters`. The Grafana dashboard gains live workers, heartbeat age and task outcomes.

**6. Probes are unchanged.** `/healthz` and `/readyz` do not look at the worker. A missing
worker must not take the API out of rotation: it still serves search, profiles and the feed,
and queued tasks wait in Redis. The worker's absence is what `SanketWorkerDown` is for.

## Consequences

- A dead worker shows within one TTL (45 seconds by default) as `sanket_worker_up 0` and an
  `unhealthy` container, and pages after five minutes if work is waiting.
- The heartbeat and the counters need the same Redis as the queue; with no Redis there is no
  worker either.
- With several workers `sanket_worker_up` is their count and the age is per worker; the series
  of a worker that is gone disappears after its TTL, so the label set follows the live workers.
- The worker still has no tracing, and request ids are not carried into tasks (ADR 0010).
- The API process reads Redis for these series, so a large number of keys under
  `sanket:worker:heartbeat:` would make a scrape slower; there is one per live worker.
- The counters are per queue name, but the heartbeat keys are not: a deployment that runs
  several differently named queues on one Redis sees all their workers in `sanket_worker_up`.
- The heartbeat thread keeps beating while the main thread is stuck in a task that the timeout
  cannot interrupt (a blocking call in native code); the alerts on queue age cover that case.
