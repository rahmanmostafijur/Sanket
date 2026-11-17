"""Feed configuration, built from the settings."""

from dataclasses import dataclass

from sanket.config import Settings


@dataclass(frozen=True)
class FeedConfig:
    channel_prefix: str = "sanket:matches"
    heartbeat_seconds: float = 15.0
    retry_ms: int = 3000
    replay_batch_size: int = 100
    buffer_size: int = 100
    max_streams: int = 200
    max_streams_per_profile: int = 5
    db_poll_seconds: float = 5.0
    max_stream_seconds: float = 3600.0


def config_from_settings(config: Settings) -> FeedConfig:
    return FeedConfig(
        channel_prefix=config.feed_channel_prefix,
        heartbeat_seconds=config.feed_heartbeat_seconds,
        retry_ms=config.feed_retry_ms,
        replay_batch_size=config.feed_replay_batch_size,
        buffer_size=config.feed_buffer_size,
        max_streams=config.feed_max_streams,
        max_streams_per_profile=config.feed_max_streams_per_profile,
        db_poll_seconds=config.feed_db_poll_seconds,
        max_stream_seconds=config.feed_max_stream_seconds,
    )
