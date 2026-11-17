"""Smoke check of a running API: `python -m sanket.smoke [--base-url http://127.0.0.1:8000]`.

Run it against a locally started stack (`python -m sanket.api`, the dev database) to see that
the main paths answer: reachability, readiness, search, creating a profile, reading it and its
matches, and the live match stream. It prints one line per check and a summary, and exits 1
when any check failed (2 for bad usage).

Endpoints that do not exist (yet) are detected from a 404, 405 or 501 and reported as
`skipped: not available`, never as a failure: the same script works before and after the
health endpoints, the live feed or authentication are deployed. When authentication is
required and no token was given, the affected checks are skipped as well. A token (--token or
SMOKE_TOKEN) is sent as a bearer token and is never printed. The stream is opened with a stream
token (`POST /auth/stream-token`, then `?stream_token=`) when the server issues them, as a
browser's EventSource must, and with the bearer header otherwise.

The profile check writes one profile named `smoke-<random>` and deletes it at the end, so only
point it at a development database. A base URL that is not local is refused unless
--allow-remote is given.
"""

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 10.0
TOKEN_ENV = "SMOKE_TOKEN"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
NOT_AVAILABLE = frozenset({404, 405, 501})
AUTH_REQUIRED = frozenset({401, 403})
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str

    def line(self) -> str:
        return f"[{self.status.value.upper():7}] {self.name}: {self.detail}"


@dataclass(frozen=True)
class Reply:
    """An answer, or why there is none. `call` never raises."""

    method: str
    path: str
    status: int | None = None
    body: Any = None
    content_type: str = ""
    error: str | None = None

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def unreachable(self) -> bool:
        return self.status is None


def passed(name: str, detail: str) -> CheckResult:
    return CheckResult(name, Status.PASS, detail)


def failed(name: str, detail: str) -> CheckResult:
    return CheckResult(name, Status.FAIL, detail)


def skipped(name: str, reason: str) -> CheckResult:
    return CheckResult(name, Status.SKIPPED, f"skipped: {reason}")


def call(
    client: httpx.Client, method: str, path: str, *, anonymous: bool = False, **kwargs: Any
) -> Reply:
    """One request. A transport error is returned in `error`; a non-JSON body is `None`.

    `anonymous` leaves out the client's Authorization header, for a request that carries its
    own credential (a stream token in the query string).
    """
    try:
        request = client.build_request(method, path, **kwargs)
        if anonymous:
            request.headers.pop("authorization", None)
        response = client.send(request, stream=True)
        try:
            content_type = response.headers.get("content-type", "")
            if content_type.startswith("text/event-stream"):
                return Reply(method, path, response.status_code, None, content_type)
            response.read()
            try:
                body = response.json()
            except ValueError:
                body = None
            return Reply(method, path, response.status_code, body, content_type)
        finally:
            response.close()
    except httpx.HTTPError as error:
        return Reply(method, path, error=type(error).__name__)


def unavailable(name: str, reply: Reply, has_token: bool) -> CheckResult | None:
    """The result for an endpoint that is missing or needs a token we do not have, else None."""
    if reply.unreachable:
        return failed(name, f"{reply.label} failed: {reply.error}")
    if reply.status in NOT_AVAILABLE:
        return skipped(name, f"not available ({reply.label} -> {reply.status})")
    if reply.status in AUTH_REQUIRED:
        if has_token:
            return failed(name, f"{reply.label} -> {reply.status}: the token was rejected")
        return skipped(name, f"authentication required ({reply.label} -> {reply.status})")
    return None


def _expect(name: str, reply: Reply, has_token: bool, ok_statuses: Sequence[int]) -> CheckResult:
    """Pass when the status is expected, else the unavailable/failed result."""
    missing = unavailable(name, reply, has_token)
    if missing is not None:
        return missing
    if reply.status in ok_statuses:
        return passed(name, f"{reply.label} -> {reply.status}")
    return failed(name, f"{reply.label} -> {reply.status}, expected {list(ok_statuses)}")


# -- the checks ----------------------------------------------------------------------------------


def check_reachable(client: httpx.Client) -> tuple[CheckResult, bool]:
    """Liveness: /healthz where it exists, else the API docs. Returns (result, reachable)."""
    name = "reachable"
    health = call(client, "GET", "/healthz")
    if health.unreachable:
        return failed(name, f"{health.label} failed: {health.error}"), False
    if health.status == 200:
        return passed(name, f"{health.label} -> 200"), True
    if health.status in NOT_AVAILABLE:
        docs = call(client, "GET", "/docs")
        if docs.status == 200:
            return passed(name, "/healthz not available; GET /docs -> 200"), True
        return failed(name, f"/healthz not available and GET /docs -> {docs.status}"), True
    return failed(name, f"{health.label} -> {health.status}"), True


def check_ready(client: httpx.Client) -> CheckResult:
    reply = call(client, "GET", "/readyz")
    if reply.status in NOT_AVAILABLE:
        return skipped("ready", f"not available ({reply.label} -> {reply.status})")
    return _expect("ready", reply, False, [200])


def check_search(client: httpx.Client, has_token: bool) -> CheckResult:
    name = "search"
    reply = call(client, "GET", "/search", params={"q": "engineer", "limit": 5})
    problem = unavailable(name, reply, has_token)
    if problem is not None:
        return problem
    body = reply.body
    if reply.status != 200 or not isinstance(body, dict):
        return failed(name, f"{reply.label} -> {reply.status}, expected a JSON object")
    items = body.get("items")
    if not isinstance(items, list) or not isinstance(body.get("total_candidates"), int):
        return failed(name, "the response has no items list and total_candidates")
    if any(not isinstance(item, dict) or "job_id" not in item for item in items):
        return failed(name, "a search result has no job_id")
    return passed(name, f"{reply.label} -> 200 with {len(items)} items")


def new_profile_body() -> dict[str, Any]:
    return {
        "name": f"smoke-{uuid.uuid4().hex[:12]}",
        "summary": "smoke test profile, safe to delete",
        "desired_titles": ["Smoke Test Engineer"],
    }


def check_profile_create(client: httpx.Client, has_token: bool) -> tuple[CheckResult, int | None]:
    """Create the smoke profile; returns (result, its id when created)."""
    name = "profile create"
    reply = call(client, "POST", "/profiles", json=new_profile_body())
    problem = unavailable(name, reply, has_token)
    if problem is not None:
        return problem, None
    body = reply.body
    if reply.status not in (200, 201) or not isinstance(body, dict):
        return failed(name, f"{reply.label} -> {reply.status}, expected 201"), None
    profile_id = body.get("id")
    if not isinstance(profile_id, int):
        return failed(name, "the response has no integer id"), None
    return passed(name, f"{reply.label} -> {reply.status}, id {profile_id}"), profile_id


def check_profile_read(client: httpx.Client, profile_id: int, has_token: bool) -> CheckResult:
    name = "profile read"
    reply = call(client, "GET", f"/profiles/{profile_id}")
    problem = unavailable(name, reply, has_token)
    if problem is not None:
        return problem
    body = reply.body
    if reply.status != 200 or not isinstance(body, dict) or body.get("id") != profile_id:
        return failed(name, f"{reply.label} -> {reply.status}, expected the profile back")
    return passed(name, f"{reply.label} -> 200, embedding_status {body.get('embedding_status')}")


def check_matches(client: httpx.Client, profile_id: int, has_token: bool) -> CheckResult:
    name = "match list"
    reply = call(client, "GET", f"/profiles/{profile_id}/matches", params={"limit": 5})
    problem = unavailable(name, reply, has_token)
    if problem is not None:
        return problem
    body = reply.body
    if reply.status != 200 or not isinstance(body, dict) or not isinstance(body.get("items"), list):
        return failed(name, f"{reply.label} -> {reply.status}, expected an items list")
    return passed(name, f"{reply.label} -> 200 with {len(body['items'])} matches")


def _open_stream(client: httpx.Client, profile_id: int) -> tuple[Reply, str]:
    """Open the stream the way a browser would when the server issues stream tokens (mint one
    with the bearer credential, then send only the token in the query string), else with the
    bearer header. Returns the answer and how it was authenticated."""
    path = f"/profiles/{profile_id}/matches/stream"
    accept = {"Accept": "text/event-stream"}
    minted = call(client, "POST", "/auth/stream-token", json={"profile_id": profile_id})
    body = minted.body
    if minted.status == 200 and isinstance(body, dict) and isinstance(body.get("token"), str):
        parameter = body.get("query_parameter")
        key = parameter if isinstance(parameter, str) else "stream_token"
        opened = call(
            client, "GET", path, params={key: body["token"]}, headers=accept, anonymous=True
        )
        return opened, "stream token"
    return call(client, "GET", path, headers=accept), "bearer header"


def check_stream(client: httpx.Client, profile_id: int, has_token: bool) -> CheckResult:
    """The live feed answers with an event stream. Only the headers are read."""
    name = "match stream"
    reply, how = _open_stream(client, profile_id)
    problem = unavailable(name, reply, has_token)
    if problem is not None:
        return problem
    if reply.status != 200 or not reply.content_type.startswith("text/event-stream"):
        return failed(name, f"{reply.label} -> {reply.status} {reply.content_type!r} ({how})")
    return passed(name, f"{reply.label} -> 200 text/event-stream ({how})")


def check_cleanup(client: httpx.Client, profile_id: int, has_token: bool) -> CheckResult:
    return _expect(
        "profile cleanup",
        call(client, "DELETE", f"/profiles/{profile_id}"),
        has_token,
        [204, 200],
    )


# -- running them --------------------------------------------------------------------------------


def _profile_checks(client: httpx.Client, profile_id: int, has_token: bool) -> list[CheckResult]:
    steps: list[Callable[[httpx.Client, int, bool], CheckResult]] = [
        check_profile_read,
        check_matches,
        check_stream,
    ]
    results = [step(client, profile_id, has_token) for step in steps]
    results.append(check_cleanup(client, profile_id, has_token))
    return results


def run_smoke(client: httpx.Client, *, has_token: bool = False) -> list[CheckResult]:
    """Every check, in order. Checks that depend on the profile are skipped without one."""
    reachable, is_up = check_reachable(client)
    if not is_up:
        reason = "the API is not reachable"
        names = ["ready", "search", "profile create", "profile read", "match list", "match stream"]
        return [reachable, *(skipped(name, reason) for name in names)]
    results = [reachable, check_ready(client), check_search(client, has_token)]
    created, profile_id = check_profile_create(client, has_token)
    results.append(created)
    if profile_id is None:
        no_profile = "no profile was created"
        results.extend(skipped(name, no_profile) for name in ("profile read", "match list"))
        results.append(skipped("match stream", no_profile))
        return results
    return [*results, *_profile_checks(client, profile_id, has_token)]


def summary_line(results: Sequence[CheckResult]) -> str:
    counts = {status: sum(r.status is status for r in results) for status in Status}
    verdict = "FAILED" if counts[Status.FAIL] else "OK"
    return (
        f"smoke {verdict}: {counts[Status.PASS]} passed, {counts[Status.FAIL]} failed, "
        f"{counts[Status.SKIPPED]} skipped"
    )


def is_local(base_url: str) -> bool:
    return urlparse(base_url).hostname in LOCAL_HOSTS


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base-url", default=os.environ.get("SMOKE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--token", default=None, help=f"bearer token for an API that needs one (or set {TOKEN_ENV})"
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--allow-remote", action="store_true", help="allow a base URL that is not local"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    """Run the checks and print the report; `transport` lets tests replace the network."""
    args = parse_args(argv)
    if not args.allow_remote and not is_local(args.base_url):
        print(f"refusing {args.base_url!r}: not a local address (use --allow-remote)")
        return EXIT_USAGE
    token = args.token or os.environ.get(TOKEN_ENV)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(
        base_url=args.base_url, headers=headers, timeout=args.timeout, transport=transport
    ) as client:
        results = run_smoke(client, has_token=bool(token))
    for result in results:
        print(result.line())
    print(summary_line(results))
    return EXIT_FAILED if any(r.status is Status.FAIL for r in results) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
