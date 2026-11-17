# Live match feed (API users and operators)

A per-profile stream of new matches over Server-Sent Events. Why it is built this way
is in [adr/0007-live-match-feed.md](adr/0007-live-match-feed.md); how matches are made
is in [matching.md](matching.md).

```
worker: match committed ──► RedisMatchNotifier ──► PUBLISH sanket:matches:{profile_id}
                                                         │
API:  GET /profiles/{id}/matches/stream ◄── SUBSCRIBE ───┘   (event = the stored row)
         ▲                  └── no Redis: poll the database every FEED_DB_POLL_SECONDS
         └── Last-Event-ID: replay stored matches after that id, then live
```

## The endpoint

`GET /profiles/{profile_id}/matches/stream`, `Content-Type: text/event-stream`. It acts
for the same owner as the other profile routes: a profile that is not yours (or does not
exist) is `404`, so ids reveal nothing. Authentication is not built yet.

| Status | When |
|---|---|
| 200 | The stream. |
| 400 | `Last-Event-ID` (or `last_event_id`) is not a match id: a non-negative integer. |
| 404 | No such profile for this owner. |
| 429 | Too many open streams (per profile or per process); see `Retry-After`. |

What arrives:

```
retry: 3000                      <- reconnect delay hint, first thing sent

id: 41                           <- bare id: your resume point when you connected fresh
                                    (no event is delivered for it)

id: 42                           <- the persisted match id
event: match
data: {"id":42,"job_id":7,"score":0.81,"status":"active","components":{...},
       "created_at":"...","updated_at":"...","job":{...},"reactivated":false}

: ping                           <- heartbeat comment, ignore
```

`data` is one line of JSON: the same fields as an item of `GET /profiles/{id}/matches`
(job summary, link and credit line included, so always link to the original listing),
plus `reactivated`, true when a match that had been withdrawn is active again. It is
read from the database when the event is sent, so it shows the match as it is now.

### Resuming

- **Header `Last-Event-ID: N`**: what a browser sends by itself when it reconnects. The
  stored active matches with an id above `N` are sent first, in id order (in batches of
  `FEED_REPLAY_BATCH_SIZE`), then live ones.
- **Query `?last_event_id=N`**: the same for the first request, because `EventSource`
  cannot set headers. If both are given the header wins (on a reconnect it is newer).
- **Neither**: live matches only. A client that wants what exists already lists it first
  (`GET /profiles/{id}/matches`) and starts the stream with the last `next_after_id` as
  `last_event_id`, so nothing falls between the two.
- A blank value counts as none; anything else that is not a non-negative integer is `400`.

### What to expect

- **At least once.** The same id can arrive twice (after a reconnect, or when a message
  and a replay overlap). Keep the ids you have shown and ignore repeats. A match is not
  skipped: one that is committed after your position is either replayed or announced,
  and a lost announcement is found by the next heartbeat's catch-up.
- **New and reactivated matches only.** Withdrawn matches are not streamed; list with
  `include_withdrawn=true` to see them. A match that was withdrawn and came back keeps
  its old id, so a reconnecting client whose position is already past it is not replayed
  it; list the matches when you need the whole picture, use the stream for speed.
- **Order.** Replay is in id order. Live events come in the order they were announced,
  which is nearly always id order.
- **The server closes the stream** when you fall too far behind (`FEED_BUFFER_SIZE`
  events waiting), when Redis fails, and after `FEED_MAX_STREAM_SECONDS`. Reconnect with
  `Last-Event-ID`; nothing is lost. `EventSource` does this by itself.
- **No Redis**: if `REDIS_URL` is unset or Redis is down when you connect, the stream
  polls the database every `FEED_DB_POLL_SECONDS`; latency is that interval instead of
  immediate. Replay and heartbeats work the same.

## Clients

curl (`-N` turns off its output buffering):

```bash
# live only
curl -N http://127.0.0.1:8000/profiles/1/matches/stream

# everything after match 40, then live
curl -N -H "Last-Event-ID: 40" http://127.0.0.1:8000/profiles/1/matches/stream
curl -N "http://127.0.0.1:8000/profiles/1/matches/stream?last_event_id=40"
```

A browser:

```js
const seen = new Set();
const source = new EventSource("/profiles/1/matches/stream?last_event_id=40");

source.addEventListener("match", (event) => {
  if (seen.has(event.lastEventId)) return;          // at least once: ignore repeats
  seen.add(event.lastEventId);
  const match = JSON.parse(event.data);
  console.log(match.job.title, match.score, match.reactivated);
});
source.onerror = () => { /* the browser reconnects and sends Last-Event-ID itself */ };
```

`EventSource` remembers the last id it saw and sends it as `Last-Event-ID` on every
automatic reconnect; the `?last_event_id=` in the URL is only used for the very first
connection (the server prefers the header on the reconnects). An `EventSource` that gets
a `400` or `404` does not retry. It cannot send an `Authorization` header, which matters
once authentication exists (phase 8).

## Settings

All in `.env.example`; none is required.

| Setting | Default | Meaning |
|---|---|---|
| `FEED_CHANNEL_PREFIX` | `sanket:matches` | Redis channel is `<prefix>:<profile id>`. Worker and API must agree. |
| `FEED_HEARTBEAT_SECONDS` | 15 | Idle time before the catch-up query and a `: ping`. Keep it below your proxy's read timeout. |
| `FEED_RETRY_MS` | 3000 | The `retry:` hint, and the basis of `Retry-After` on a 429. |
| `FEED_REPLAY_BATCH_SIZE` | 100 | Matches read per query when replaying, and events handled per round. |
| `FEED_BUFFER_SIZE` | 100 | Events a connection may have waiting before it is dropped. |
| `FEED_MAX_STREAMS` | 200 | Open streams per API process. |
| `FEED_MAX_STREAMS_PER_PROFILE` | 5 | Open streams per profile. |
| `FEED_DB_POLL_SECONDS` | 5 | Polling interval without Redis. |
| `FEED_MAX_STREAM_SECONDS` | 3600 | A stream is closed after this long; the client reconnects. |

`REDIS_URL` and `REDIS_TIMEOUT_SECONDS` are shared with the queue. The worker publishes
with the notifier built from `REDIS_URL`; `python -m sanket.matching ... --apply --inline`
publishes too. Without `REDIS_URL` nothing is published and `notified_at` is still set (see
[matching.md](matching.md#the-notifier-hook)).

## Operating it

- Behind nginx: `proxy_buffering off` (the response already sends `X-Accel-Buffering: no`),
  `proxy_read_timeout` above the heartbeat (for example 60s), and HTTP/2 for many tabs.
- Look at who is subscribed: `redis-cli pubsub numsub sanket:matches:1`. After a client
  leaves the number drops back at once.
- Try it without a client: open the stream with curl, then
  `redis-cli publish sanket:matches:1 '{"match_id":1,"profile_id":1,"job_id":1,"score":0.9,"reactivated":false}'`
  (only a match that exists in the database and is active is sent).
- Redis carries only ids and the score, never owner or job text, but keep it off public
  networks: anyone who can subscribe sees them.
