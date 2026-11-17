"""A Redis pub/sub subscription feeding a bounded buffer, on the event loop.

`Subscription.open` subscribes and starts a task that moves published events into a queue of
at most `buffer_size`. The consumer takes from the queue at its own pace. When the queue is
full the subscription gives up (`overflowed`): a consumer that cannot keep up is not allowed to
make the process hold more and more events, and the stream is closed so the client resumes
from the database with Last-Event-ID. A Redis error ends the task too (`failed`).
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable

from redis.asyncio import Redis as AsyncRedis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from sanket.feed.events import MatchEvent, decode

logger = logging.getLogger(__name__)

RedisFactory = Callable[[], AsyncRedis]
# How long one wait for a message lasts; a message wakes it at once.
PUMP_WAIT_SECONDS = 1.0


class Subscription:
    def __init__(self, client: AsyncRedis, pubsub: PubSub, buffer_size: int) -> None:
        self._client = client
        self._pubsub = pubsub
        # None marks "the task stopped", so a consumer waiting on the queue wakes up.
        self._queue: asyncio.Queue[MatchEvent | None] = asyncio.Queue(buffer_size)
        self._task: asyncio.Task[None] | None = None
        self.overflowed = False
        self.failed = False

    @classmethod
    async def open(
        cls, factory: RedisFactory, channel: str, buffer_size: int
    ) -> "Subscription | None":
        """Subscribe to `channel`; None when Redis cannot be reached."""
        client = factory()
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(channel)
        except (RedisError, OSError) as error:
            logger.warning("Feed cannot subscribe (%s); falling back to the database", error)
            await _close(pubsub, client)
            return None
        except BaseException:
            await _close(pubsub, client)
            raise
        subscription = cls(client, pubsub, buffer_size)
        subscription._task = asyncio.create_task(subscription._pump())
        return subscription

    async def take(self, limit: int, timeout: float) -> list[MatchEvent]:
        """Wait up to `timeout` for an event, then take what else is waiting (up to `limit`)."""
        try:
            first = await asyncio.wait_for(self._queue.get(), max(timeout, 0))
        except TimeoutError:
            return []
        events = [] if first is None else [first]
        while len(events) < limit and not self._queue.empty():
            event = self._queue.get_nowait()
            if event is not None:
                events.append(event)
        return events

    async def close(self) -> None:
        """Stop the task and release the connection; safe to call more than once."""
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await _close(self._pubsub, self._client)

    async def _pump(self) -> None:
        try:
            while True:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=PUMP_WAIT_SECONDS
                )
                if message is not None and not self._offer(message.get("data")):
                    return
        except (RedisError, OSError) as error:
            logger.warning("Feed subscription lost (%s)", error)
            self.failed = True
            self._wake()

    def _offer(self, raw: bytes | str | None) -> bool:
        """Queue one message; False when the buffer is full and the pump must stop."""
        if raw is None:
            return True
        try:
            event = decode(raw)
        except ValueError:
            logger.warning("Feed ignored a message that is not a match event")
            return True
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.overflowed = True
            return False
        return True

    def _wake(self) -> None:
        # A full queue already has something for the consumer to wake on.
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(None)


async def _close(pubsub: PubSub, client: AsyncRedis) -> None:
    for closer in (pubsub.aclose, client.aclose):
        try:
            await closer()
        except (RedisError, OSError):
            logger.debug("Closing a feed connection failed", exc_info=True)
