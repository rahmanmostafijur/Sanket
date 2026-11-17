"""/metrics shows the worker: live workers, heartbeat age and the task counters (ADR 0011).

The API reads them from Redis at scrape time, so these tests put a heartbeat and counters in a
fakeredis and scrape the real app, with and without a reachable Redis.
"""

import time
from typing import Any

import fakeredis
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import Engine

from sanket.observability.worker_metrics import CACHE_SECONDS, WorkerCollector
from sanket.queue.rq_queue import RqTaskQueue
from sanket.queue.stats import Outcome, record_outcome
from sanket.worker.heartbeat import Heartbeat
from tests.queue_helpers import CFG, registry_of, run_burst
from tests.test_api_ops import client_for, scrape

QUEUE = CFG.queue_name


class Clock:
    def __init__(self, now: float = 5000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def rq_queue() -> RqTaskQueue:
    return RqTaskQueue(fakeredis.FakeStrictRedis(), CFG)


def beat(queue: RqTaskQueue, name: str, moment: float | None = None) -> None:
    clock = (lambda: moment) if moment is not None else time.time
    Heartbeat(queue.connection, name, interval_seconds=10, ttl_seconds=45, clock=clock).beat()


# --- through the API --------------------------------------------------------------------------


def test_a_live_worker_is_counted_with_its_heartbeat_age(clean_db: Engine) -> None:
    queue = rq_queue()
    beat(queue, "worker-a")

    body = scrape(client_for(clean_db, queue))

    assert "sanket_worker_up 1.0" in body
    assert 'sanket_worker_last_heartbeat_age_seconds{worker="worker-a"}' in body


def test_without_any_heartbeat_no_worker_is_up_and_no_age_is_exported(clean_db: Engine) -> None:
    body = scrape(client_for(clean_db, rq_queue()))

    assert "sanket_worker_up 0.0" in body
    assert "sanket_worker_last_heartbeat_age_seconds{" not in body
    # The queue gauges are still there, so "no worker while tasks wait" can be alerted on.
    assert "sanket_queue_up 1.0" in body


def test_a_worker_that_stopped_beating_drops_out_of_the_count(clean_db: Engine) -> None:
    queue = rq_queue()
    beat(queue, "worker-a")
    queue.connection.pexpire("sanket:worker:heartbeat:worker-a", 1)
    time.sleep(0.01)

    assert "sanket_worker_up 0.0" in scrape(client_for(clean_db, queue))


def test_task_counters_are_exported_by_queue_and_task(clean_db: Engine) -> None:
    queue = rq_queue()
    record_outcome(queue.connection, QUEUE, "match_job", Outcome.PROCESSED)
    record_outcome(queue.connection, QUEUE, "match_job", Outcome.PROCESSED)
    record_outcome(queue.connection, QUEUE, "embed_profile", Outcome.RETRIED)
    record_outcome(queue.connection, QUEUE, "embed_profile", Outcome.FAILED)

    body = scrape(client_for(clean_db, queue))

    assert f'sanket_worker_jobs_processed_total{{queue="{QUEUE}",task="match_job"}} 2.0' in body
    assert f'sanket_worker_jobs_retried_total{{queue="{QUEUE}",task="embed_profile"}} 1.0' in body
    assert f'sanket_worker_jobs_failed_total{{queue="{QUEUE}",task="embed_profile"}} 1.0' in body


def test_counters_written_by_the_real_runner_reach_the_scrape(clean_db: Engine) -> None:
    queue = rq_queue()
    queue.enqueue("work", {}, key="a")
    run_burst(queue, registry_of(work=lambda payload, context: None))

    body = scrape(client_for(clean_db, queue))

    assert f'sanket_worker_jobs_processed_total{{queue="{QUEUE}",task="work"}} 1.0' in body


def test_the_existing_queue_gauge_is_the_depth_and_nothing_duplicates_it(
    clean_db: Engine,
) -> None:
    queue = rq_queue()
    queue.enqueue("work", {}, key="a")
    queue.enqueue("work", {}, key="b")

    body = scrape(client_for(clean_db, queue))

    assert "sanket_queue_waiting 2.0" in body
    assert "sanket_queue_depth" not in body


def test_an_unreachable_redis_leaves_the_worker_series_out_without_failing_the_scrape(
    clean_db: Engine,
) -> None:
    unreachable = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    queue = RqTaskQueue(unreachable, CFG)

    body = scrape(client_for(clean_db, queue))

    assert "sanket_queue_up 0.0" in body
    assert "sanket_worker_up" not in body
    assert "sanket_worker_jobs" not in body


def test_without_a_redis_backed_queue_no_worker_series_are_exported(clean_db: Engine) -> None:
    assert "sanket_worker" not in scrape(client_for(clean_db))


def test_a_missing_worker_does_not_make_the_api_unready(clean_db: Engine) -> None:
    client = client_for(clean_db, rq_queue())

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert "sanket_worker_up 0.0" in scrape(client)


# --- the collector --------------------------------------------------------------------------


def families(collector: WorkerCollector) -> dict[str, Any]:
    return {family.name: family for family in collector.collect()}


def test_the_age_is_taken_at_scrape_time_from_the_wall_clock() -> None:
    queue = rq_queue()
    beat(queue, "w1", moment=1000.0)
    wall = Clock(1004.0)
    collector = WorkerCollector(queue.connection, QUEUE, 45, wall_clock=wall)

    (sample,) = families(collector)["sanket_worker_last_heartbeat_age_seconds"].samples
    assert sample.value == 4.0
    wall.now = 1007.0  # cached reading, fresh age
    (sample,) = families(collector)["sanket_worker_last_heartbeat_age_seconds"].samples
    assert sample.value == 7.0


def test_a_heartbeat_older_than_the_ttl_is_not_a_live_worker() -> None:
    queue = rq_queue()
    beat(queue, "w1", moment=1000.0)
    collector = WorkerCollector(queue.connection, QUEUE, 45, wall_clock=Clock(1046.0))

    (sample,) = families(collector)["sanket_worker_up"].samples
    assert sample.value == 0.0


def test_readings_are_cached_for_a_few_seconds_then_refreshed() -> None:
    queue = rq_queue()
    monotonic = Clock(0.0)
    wall = Clock(1000.0)
    collector = WorkerCollector(queue.connection, QUEUE, 45, monotonic, wall)
    assert families(collector)["sanket_worker_up"].samples[0].value == 0.0

    beat(queue, "w1", moment=1000.0)
    assert families(collector)["sanket_worker_up"].samples[0].value == 0.0  # still cached
    monotonic.now = CACHE_SECONDS + 1
    assert families(collector)["sanket_worker_up"].samples[0].value == 1.0


def test_a_failed_read_is_not_retried_on_every_scrape() -> None:
    reads: list[str] = []

    class Counting:
        def scan_iter(self, *args: object, **kwargs: object) -> Any:
            reads.append("scan")
            raise RedisConnectionError("down")

    monotonic = Clock(0.0)
    collector = WorkerCollector(Counting(), QUEUE, 45, monotonic)  # type: ignore[arg-type]

    assert list(collector.collect()) == []
    assert list(collector.collect()) == []
    assert reads == ["scan"]
    monotonic.now = CACHE_SECONDS + 1
    assert list(collector.collect()) == []
    assert reads == ["scan", "scan"]
