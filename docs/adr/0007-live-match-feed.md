# 0007: Live match feed

Status: accepted

## Context

Matching (ADR 0006) stores matches and hands each new one to a `MatchNotifier` after
the commit. This phase delivers them: a client watching a profile should see a new
match within a moment of it being written, survive a dropped connection without
missing or repeating anything, and cost the server a bounded amount however badly
it behaves.

Constraints that shaped the design:

- The database row is the source of truth (ADR 0006, decision 7). Whatever carries
  the notification may lose it, repeat it or deliver it late; the client must still
  end up with the right matches.
- Match ids only grow and a match keeps its id for life (ADR 0006, decision 9), so
  an id is a resume point the clients already page with (`after_id`).
- There is no authentication yet (phase 8). The feed uses whatever identifies the
  owner for the other profile routes (`get_owner_id`) and scopes the same way.
- The API runs on an event loop; Redis, the database and the client are all slow in
  different ways, and the feed must not let one of them stall the others.
- Tests use `fakeredis` and no real network.

## Options

**Transport.**

- *Polling `GET /matches?after_id=`.* Already exists. Simple, but latency is the
  polling interval and every idle client costs a query per interval.
- *WebSocket.* Two-way, which the feed does not need (the client says nothing after
  connecting), and it brings its own framing, no automatic resume, and proxies that
  treat upgrades specially.
- *Server-Sent Events.* One-way text over plain HTTP. Browsers reconnect by
  themselves and send `Last-Event-ID`, which is exactly the resume protocol above.
  Works through ordinary proxies when buffering is off, and with `curl`.

**What carries the notification from the worker to the API.**

- *Redis pub/sub.* Fire and forget: a message reaches the subscribers connected at
  that moment and is then gone. Cheap, no state to trim, no consumer groups.
- *Redis Streams.* Stored, replayable, with consumer positions. That is a second
  durable log next to `job_match`, with its own retention and its own ids, and a
  reactivated match would need an event in it anyway.
- *Postgres LISTEN/NOTIFY.* No Redis needed for the feed, but a long-lived
  connection per API process held outside the pool, an 8000-byte payload limit, and
  nothing for the worker to share with the queue it already uses.

**Redis client in the API.**

- *Synchronous client in worker threads.* One blocked thread per stream.
- *`redis.asyncio` on the event loop.* One lightweight task per stream; the
  database engine is synchronous, so its few short calls run in the thread pool.

## Decision

**1. Server-Sent Events** at `GET /profiles/{profile_id}/matches/stream`, with
`Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`,
`Connection: keep-alive`, and a `retry:` hint first.

**2. Redis pub/sub for the wake-up, the database for the content.** The worker's
`RedisMatchNotifier` publishes a compact JSON pointer to `sanket:matches:{profile_id}`
(`FEED_CHANNEL_PREFIX`): `match_id`, `profile_id`, `job_id`, `score`, `reactivated`.
Nothing owner-private goes through Redis: no owner id, no score components, no job
text. The stream turns the pointer into an event by reading the persisted row, so the
data is exactly what `GET /profiles/{id}/matches` returns (the same `MatchOut`
fields, plus `reactivated`), and a pointer to a match that has since been withdrawn
or deleted produces nothing. The notifier replaces the no-op one in the worker
registry and the matching commands when `REDIS_URL` is set; without it nothing is
published and streams poll the database.

**3. `redis.asyncio` on the event loop.** Each stream opens its own client and
dedicated subscription and closes both when it ends (a subscribed connection cannot
be shared, and a client is not bound to a loop until used). Replay and row loading
use the existing synchronous loaders in the thread pool, so no blocking call runs
on the loop.

**4. Resume by match id.** The event `id:` is the persisted match id. The client's
position is the `Last-Event-ID` header (a browser sends it when it reconnects) or
`?last_event_id=` (an `EventSource` cannot set headers on its first request); the
header wins because on a reconnect it is newer than the URL the source was opened
with. Blank means none. Anything that is not a non-negative 64-bit decimal integer is
a **400** (`{"detail": "invalid Last-Event-ID"}`): a client that sends garbage has a
bug, and silently starting live would hide it. With a position the stream first
replays the active matches after it in id order, in batches of
`FEED_REPLAY_BATCH_SIZE`, then goes live. Without one it goes live only, and the
server sends a bare `id: N` frame (no event) with the highest match id at connect, so
a reconnect always carries a cursor and nothing falls in the gap between "connected"
and "first event". A client that wants the existing matches lists them first and
passes the last `next_after_id` as `last_event_id`.

**5. Subscribe first, then replay, then dedupe.** Order of operations on connect:
subscribe to the channel (events now buffer, bounded), find the starting id, replay,
read the buffer. A match committed during the replay is either in the replay or in
the buffer or both. The stream remembers which ids the database delivered
(replay or catch-up) and drops a live event for one of them. It does **not** use
"drop anything at or below the highest id sent", for two reasons: ids are allocated
when a row is inserted, not when it commits, so a lower id can legitimately be
announced after a higher one; and a reactivated match comes back with its *old* id,
which a high-water mark would swallow.

**6. Delivery is at least once.** A client must ignore an id it has seen. The server
removes the duplicates it can know about (replay against live, within one batch) and
does not promise more. Never zero times: a match committed before the client's cursor
is replayed, one committed after is announced, and an announcement that was lost (a
Redis blip, a worker crash between commit and publish) is found by the **idle
catch-up**: after `FEED_HEARTBEAT_SECONDS` without an event the stream asks the
database for matches after the highest id it has sent, and pings only if there are
none. So a lost message costs at most one heartbeat of delay, not a missed match.

**7. Which events.** New matches and reactivated ones (`reactivated: true`), which is
exactly what the notifier is told about. Withdrawals are **not** streamed: the hook
does not report them, a client sees them with `include_withdrawn=true` or by
listing, and streaming "a match you never saw is gone" adds noise. A consequence worth
knowing: replay is by id, and a reactivated match keeps its old id, so a client that
was disconnected while a match came back, and whose position is already past that id,
is not replayed it (a live client is sent it). Clients that need a full picture list
the matches; the feed is for latency, the list is for state.

**8. Backpressure and slow consumers.** A subscription moves events into a queue of
at most `FEED_BUFFER_SIZE`. If the consumer does not drain it (the connection to the
client is slow, the send is blocked) and the queue fills, the subscription stops and
the stream is closed cleanly. The client reconnects (`EventSource` does it by
itself) with its `Last-Event-ID`, and the replay from the database fills the gap, so
dropping a slow client loses nothing and the server never holds more than the buffer.

**9. Caps.** At most `FEED_MAX_STREAMS_PER_PROFILE` (5) streams per profile and
`FEED_MAX_STREAMS` (200) per API process; beyond that **429** with `Retry-After`
(from `FEED_RETRY_MS`). The slot is released when the stream ends however it ends, and
also by the response's background task, so an abandoned response cannot leak one. A
stream also ends after `FEED_MAX_STREAM_SECONDS` (an hour) so connections rotate and a
deploy drains; the client reconnects and resumes.

**10. Redis trouble degrades, it does not fail.** If `REDIS_URL` is unset, or the
subscribe fails at connect time (short timeouts, `REDIS_TIMEOUT_SECONDS`), the
stream runs from the database: the same resume and replay, then a query for new
matches every `FEED_DB_POLL_SECONDS` (5), with heartbeats. This stays small because
replay and poll are the same function. If Redis fails *during* a stream, the stream
ends and the client reconnects, getting either a live subscription or the polling
mode. A database error also ends the stream cleanly (logged) rather than leaving a
half-finished response.

**11. Cleanup is shielded.** The server cancels a streaming response with an anyio
scope, and such a scope cancels again at every `await` inside it. Closing the Redis
subscription is an `await`, so unshielded cleanup was abandoned half way and the
connection leaked each time a client left (found by running against a real Redis and
uvicorn, reproduced in a test that cancels with an anyio scope). The subscription's
close runs in a shielded, time-bounded scope and the slot release is synchronous.

**12. `notified_at` keeps its meaning.** It is set when the notifier call returned,
which for Redis means the `PUBLISH` was accepted. Publishing to a channel with no
subscribers also returns normally and counts as delivered: that is correct, because
the row is the source of truth and a stream that connects later replays it. So
`notified_at` is now "the pointer was published", not "a client saw it"; it is still
NULL for a match whose publish failed, which is what the earlier decision wanted to be
able to find. The feed itself does not need that sweep, because the idle catch-up
reads the database; a sweep for NULL `notified_at` remains possible for other
consumers and is not built.

## Consequences

- A client needs nothing but an `EventSource` (or `curl -N`): the protocol's own
  reconnect and `Last-Event-ID` are the resume mechanism. `docs/feed.md` has examples.
- Redis pub/sub losing a message is harmless for correctness and costs at most one
  heartbeat of latency for a connected client. Redis being down is invisible to
  clients except for latency (polling every few seconds).
- Authentication is not built. The endpoint uses `get_owner_id`, so phase 8 changes
  who the owner is in one place. Note that `EventSource` cannot send an
  `Authorization` header: phase 8 must choose a cookie, a short-lived token in the
  query string, or a fetch-based client.
- Each stream holds one Redis connection and one task. At the default cap of 200
  streams per process that is 200 Redis connections per API process, fine for one or
  two processes; many processes or thousands of viewers would call for one pattern
  subscription (`sanket:matches:*`) per process fanned out in memory. The `Subscription`
  class is the seam for that change.
- Every live event costs one primary-key lookup per watching stream, and every idle
  stream one indexed range query per heartbeat. The per-profile cap bounds a single
  profile's amplification.
- The id is allocated at insert, not at commit, so a replay "after id N" can in
  principle skip a row that committed after a higher id was sent. The live
  announcement and the idle catch-up cover it in practice (the catch-up goes by
  highest id sent, so it would miss it only if its announcement was lost as well);
  closing the last gap would need a commit-ordered cursor, which is not worth its
  cost here.
- Behind nginx or another proxy the read timeout must exceed `FEED_HEARTBEAT_SECONDS`
  and buffering must be off (the response asks for it with `X-Accel-Buffering`).
  Browsers allow about six HTTP/1.1 connections per host, so many tabs need HTTP/2.
- Redis must not be reachable by clients: the channel names are guessable profile ids
  and anyone who can subscribe sees the ids and scores of new matches.
