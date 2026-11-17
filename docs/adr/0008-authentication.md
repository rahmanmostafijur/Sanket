# 0008: Authentication and authorization

Status: accepted

## Context

Until now every request acted as one configured owner (`DEFAULT_OWNER_ID`). The
profile and match routes were already scoped by an owner id, so what was missing
is a way to turn a request into a verified owner id, and to be sure nothing
reaches an owner-scoped row without it.

Constraints:

- There is no user database and no sign-up flow, and a React client is planned.
  Identity is expected to come from an external provider, so the API verifies
  credentials and does not issue or store them.
- Services and operators (scripts, a future worker, smoke tests) need a
  credential too, without running an identity provider.
- A browser `EventSource` cannot send an `Authorization` header, and the match
  stream (the live feed) is opened with one.
- Local development must stay a single command, but the shortcut must not be
  able to reach production by accident.

## Options

1. **Opaque session cookies.** Needs a session store and CSRF handling for a
   JSON API; ties the API to one browser client. Rejected.
2. **Static API keys only.** Simple, but there is no per-user identity and no
   expiry or rotation story for end users. Kept as a second credential type for
   services.
3. **Verify JWTs from an external identity provider** (JWKS) or signed with a
   shared secret. Stateless, standard, and what a hosted provider (or a small
   self-run one) issues. Chosen as the main credential.
4. **A proxy in front does the authentication** and passes a header. Moves the
   trust boundary out of the application; a request that bypasses the proxy
   is then trusted. Rejected as the only line of defence.

## Decision

**1. Bearer credentials, two kinds.** `Authorization: Bearer <credential>`, where
the credential is either

- a **JWT**, verified with `AUTH_JWT_SECRET` (HS256, at least 32 characters) and/or
  against the provider's keys at `AUTH_JWKS_URL` (RS256, ES256; keys cached for an
  hour, fetched with a 5 second timeout). The accepted algorithms are fixed per
  key type and never read from the token header (no `none`, no algorithm
  confusion). `exp` is required; `iss` and `aud` are enforced when
  `AUTH_ISSUER` / `AUTH_AUDIENCE` are set; 30 seconds of clock skew is allowed.
- a **static API key** from `AUTH_API_KEYS` (`owner=key,...`, keys of at least 24
  random characters), compared as SHA-256 digests with `hmac.compare_digest`.

**2. The owner id is the verified subject.** For a JWT it is the claim named by
`AUTH_OWNER_CLAIM` (default `sub`), which must be a printable string without
whitespace of at most 200 characters; for a key it is the owner the operator
named in the setting. The owner id is never taken from the URL, the body or a
header the caller controls. Operators choose key owner names that cannot collide
with a provider subject unless they mean to.

**3. 401, 403, 404.** No or invalid credential: 401 with `WWW-Authenticate:
Bearer` (the message never contains the credential). A valid identity that lacks
the permission is 403: with `AUTH_REQUIRED_SCOPE` set, a token whose `scope` /
`scp` claim lacks it is refused (static keys carry every scope). A resource that
belongs to another owner is 404, exactly like a missing one, so ids reveal
nothing (this was already the case for profiles and matches).

**4. One dependency scopes every owner route.** `get_owner_id` in `api/deps.py`
returns the authenticated owner and is the only way routes learn who is calling;
every profile and match query takes it. It is also what the feed endpoint uses,
so the feed is scoped by the same rule with no extra code. `get_principal`
returns the richer `Principal` (owner, method, scopes), and `create_app`'s
`dependencies` still guard every API route on top of it.

**5. Development bypass.** `AUTH_DEV_BYPASS=true` lets a request *without* a
credential act as `DEFAULT_OWNER_ID`. It needs `ENVIRONMENT=development` as well:
the API refuses to start with the flag in any other environment, and also
refuses to start when no credential type is configured and the bypass is off
(`sanket.runtime_checks.check_api`). A credential that is sent must still be
valid, so the bypass never masks a broken client. The default is off; the
example `.env` turns it on for local work.

**6. Public and protected routes.** `/healthz` and `/readyz` are public (they
return no data about the system beyond up or down). `/metrics` has its own
token (ADR 0010). `GET /search` **requires a credential by default**, because
each query costs an embedding call; `SEARCH_PUBLIC=true` opens it (it is then
rate limited by client address, ADR 0009). Every other route requires a
credential.

**7. How the feed authenticates.** The stream is `GET
/profiles/{id}/matches/stream`. A client that can set headers (a fetch-based
SSE client, a native app, a service) sends the bearer credential as usual. A
browser `EventSource` cannot, so there is a short-lived signed token:
`POST /auth/stream-token {"profile_id": n}` (bearer-authenticated, and a profile
that is not the caller's is 404) returns a token to open the stream with
`?stream_token=...`. The token is `v1.<payload>.<HMAC-SHA256>`, signed with
`AUTH_STREAM_TOKEN_SECRET`, carries the owner id, the exact path it opens and an
expiry (60 seconds by default), and is accepted only when the request has no
`Authorization` header and the request path equals the token path. It therefore
opens one stream for about a minute, cannot mint another token, and is useless on
any other route. Query strings are never written to the access log or to
metrics (only the path is), and the token is not logged anywhere else. Without
the secret the endpoint answers 404 and the query parameter is ignored. The
alternative of a cookie was rejected for the same reasons as option 1.

## Consequences

- Production needs a provider (or a shared secret) and key distribution outside
  this repository; `docs/deploy.md` lists the settings and how to rotate them.
  Rotating `AUTH_JWT_SECRET` invalidates every issued token; rotating a static
  key means adding the new one next to the old and removing the old later
  (entries are a list).
- An owner has no record in the database until it creates a profile; revoking a
  user is done at the provider (tokens are short-lived) or by removing a key.
- There are no roles. 403 exists for the scope check only; finer permissions
  would add scopes per route group.
- Tokens are not revocable before they expire; keep provider token lifetimes
  short. The stream token's one-minute life limits what a leaked URL is worth.
- Existing local `.env` files need `AUTH_DEV_BYPASS=true` (or a credential) to
  keep working.
