# 0009: Rate limiting

Status: accepted

## Context

The API is reachable by authenticated users and, for search and the job routes,
by anyone. Search costs an embedding call per query (a small, metered free-tier
quota), profile writes queue work, and unauthenticated callers can guess
credentials. One caller must not be able to exhaust any of these for everyone.
The API may run as several processes, and Redis is already part of the stack
for the task queue (ADR 0005).

## Options

1. **Limit at the reverse proxy only.** Cheap, but the proxy sees addresses, not
   owners, and the limit does not exist in development or in a plain container.
2. **A library (SlowAPI and similar).** Pulls in another dependency for a
   per-process or Redis counter and ties limits to its decorators; per-owner
   identities and an injectable clock for tests need custom code anyway.
3. **A small in-repo limiter**: counters in Redis when configured, in memory
   otherwise. Chosen.

## Decision

**Algorithm.** Sliding window counter: two fixed-window counters per caller and
bucket; the estimate for the last window is `previous x (1 - elapsed fraction) +
current`. It avoids the double burst a fixed window allows at its boundary with
O(1) state. A refused request is not counted, so a client that backs off
recovers. The clock is injectable.

**Identity.** The owner id when the credential is valid, otherwise the client
address, so unauthenticated and failing callers share their address's budget
(this also slows credential guessing). The address is the connection's peer.
Behind reverse proxies, `TRUSTED_PROXY_HOPS=n` takes the entry `n` places from
the end of `X-Forwarded-For`; entries before it can be forged by the caller and
are ignored. The default is 0, which is the only safe value without a proxy.

**Buckets.** `default` (`RATE_LIMIT_DEFAULT_REQUESTS`, 120 per window) for the
profile and auth routes, and a stricter `search` bucket
(`RATE_LIMIT_SEARCH_REQUESTS`, 30 per window) for `GET /search`. The window is
`RATE_LIMIT_WINDOW_SECONDS` (60). The numbers are starting points, not measured.

**Storage.** With `REDIS_URL`, counters live in Redis (`sanket:rl:<bucket>:<identity>:<window>`,
expiring after two windows), shared by every API process. If Redis fails, that
request is counted in memory instead and the failure is logged once a minute:
an outage never blocks the API and never leaves it unlimited. Without
`REDIS_URL` counters are per process, which is exact for one process and a
looser limit (`n` x) for `n`.

**Answer.** `429` with the error envelope (`rate_limited`) and `Retry-After`
(whole seconds), `X-RateLimit-Limit` and `X-RateLimit-Remaining`; successful
responses carry the last two.

**Exemptions.** `/healthz`, `/readyz` and `/metrics` do not use the dependency.
Streaming requests (`Accept: text/event-stream`) are never counted: a stream is
one long request and counting it per request would be meaningless; the feed is
bounded by a connection cap instead (ADR 0007). A route opts in by depending on
`RateLimit("default" | "search")`.

## Consequences

- The limit protects the API process, not the host: a flood still costs a
  request parse and a Redis round trip, so a proxy or firewall limit in front is
  still advisable in production.
- Memory counters are pruned when more than 10,000 callers are tracked.
- With several processes and no Redis the effective limit is multiplied; set
  `REDIS_URL` for production.
- Limits are per bucket, not per route, so a client can spend its `default`
  budget on any route in it.
