"""Publish new matches to Redis, one channel per profile.

`RedisMatchNotifier` is the `MatchNotifier` the worker and the matching commands use when
REDIS_URL is set. Publishing is one quick command on a client with short timeouts; a Redis
error propagates, which the matcher logs and survives (the match stays stored with
`notified_at` NULL). Publishing to a channel nobody listens on succeeds and counts as delivered:
the database row is the source of truth and a stream that connects later replays from it.
"""

import logging

from redis import Redis

from sanket.config import Settings
from sanket.feed.events import channel_for, encode, event_from_record
from sanket.matching.notify import MatchNotifier, MatchRecord, NoopNotifier
from sanket.queue.connection import redis_connection

logger = logging.getLogger(__name__)


class RedisMatchNotifier:
    def __init__(self, connection: Redis, channel_prefix: str) -> None:
        self._redis = connection
        self._prefix = channel_prefix

    def notify(self, match: MatchRecord) -> None:
        channel = channel_for(self._prefix, match.profile_id)
        subscribers = self._redis.publish(channel, encode(event_from_record(match)))
        logger.debug("Published match %d to %d subscribers", match.match_id, subscribers)


def notifier_from_settings(config: Settings) -> MatchNotifier:
    """The Redis notifier, or the no-op one when REDIS_URL is not set."""
    if config.redis_url is None:
        return NoopNotifier()
    return RedisMatchNotifier(redis_connection(config), config.feed_channel_prefix)
