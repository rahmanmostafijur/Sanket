"""The smoke check against a fake API: no network, no database."""

import json
from collections.abc import Callable

import httpx
import pytest

from sanket import smoke
from sanket.smoke import Status

SECRET = "tok-super-secret-value"
PROFILE_ID = 7

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def clean_smoke_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's own SMOKE_* variables must not change what the tests exercise."""
    monkeypatch.delenv(smoke.TOKEN_ENV, raising=False)
    monkeypatch.delenv("SMOKE_BASE_URL", raising=False)


def json_response(status: int, body: object = None) -> httpx.Response:
    return httpx.Response(status, json=body)


class FakeApi:
    """A tiny API. `missing` paths answer 404; `overrides` replace a route's answer."""

    def __init__(
        self,
        missing: tuple[str, ...] = (),
        overrides: dict[str, Handler] | None = None,
        require_token: str | None = None,
        stream_token: str | None = None,
    ) -> None:
        self.missing = missing
        self.overrides = overrides or {}
        self.require_token = require_token
        # When set, the API issues this stream token and opens streams only for it.
        self.stream_token = stream_token
        self.accepted_stream_token = stream_token
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = f"{request.method} {request.url.path}"
        if any(route.endswith(path) for path in self.missing):
            return json_response(404, {"detail": "Not Found"})
        wanted = f"Bearer {self.require_token}"
        token_ok = (
            self.accepted_stream_token is not None
            and request.url.path.endswith("/matches/stream")
            and request.url.params.get("stream_token") == self.accepted_stream_token
        )
        if (
            self.require_token is not None
            and not token_ok
            and request.headers.get("authorization") != wanted
        ):
            return json_response(401, {"detail": "unauthorised"})
        if route == f"GET /profiles/{PROFILE_ID}/matches/stream" and self.stream_token:
            return self.stream_with_token(request)
        if route in self.overrides:
            return self.overrides[route](request)
        return self.default(request, route)

    def stream_with_token(self, request: httpx.Request) -> httpx.Response:
        if request.url.params.get("stream_token") != self.accepted_stream_token:
            return json_response(401, {"error": {"code": "unauthenticated"}})
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"")

    def default(self, request: httpx.Request, route: str) -> httpx.Response:
        if route == "POST /auth/stream-token" and self.stream_token:
            return json_response(
                200,
                {
                    "token": self.stream_token,
                    "path": f"/profiles/{PROFILE_ID}/matches/stream",
                    "query_parameter": "stream_token",
                    "expires_in": 60,
                },
            )
        if route == "GET /healthz" or route == "GET /readyz" or route == "GET /docs":
            return json_response(200, {"status": "ok"})
        if route == "GET /search":
            return json_response(
                200, {"items": [{"job_id": 1, "title": "Engineer"}], "total_candidates": 1}
            )
        if route == "POST /profiles":
            return json_response(201, {"id": PROFILE_ID, "embedding_status": "pending"})
        if route == f"GET /profiles/{PROFILE_ID}":
            return json_response(200, {"id": PROFILE_ID, "embedding_status": "pending"})
        if route == f"GET /profiles/{PROFILE_ID}/matches":
            return json_response(200, {"items": [], "next_after_id": None, "has_more": False})
        if route == f"GET /profiles/{PROFILE_ID}/matches/stream":
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"")
        if route == f"DELETE /profiles/{PROFILE_ID}":
            return httpx.Response(204)
        return json_response(404, {"detail": "Not Found"})

    def routes(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.requests]


def run(api: FakeApi, *, token: str | None = None) -> dict[str, smoke.CheckResult]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(
        base_url="http://api.test", transport=httpx.MockTransport(api), headers=headers
    ) as client:
        results = smoke.run_smoke(client, has_token=token is not None)
    return {result.name: result for result in results}


def statuses(results: dict[str, smoke.CheckResult]) -> dict[str, Status]:
    return {name: result.status for name, result in results.items()}


def test_every_check_passes_against_a_complete_api() -> None:
    api = FakeApi()

    results = run(api)

    assert set(statuses(results).values()) == {Status.PASS}
    assert list(results) == [
        "reachable",
        "ready",
        "search",
        "profile create",
        "profile read",
        "match list",
        "match stream",
        "profile cleanup",
    ]
    assert api.routes()[-1] == f"DELETE /profiles/{PROFILE_ID}"


def test_an_api_without_health_endpoints_or_a_stream_still_passes() -> None:
    api = FakeApi(missing=("/healthz", "/readyz", "/stream"))

    results = run(api)

    assert statuses(results) == {
        "reachable": Status.PASS,
        "ready": Status.SKIPPED,
        "search": Status.PASS,
        "profile create": Status.PASS,
        "profile read": Status.PASS,
        "match list": Status.PASS,
        "match stream": Status.SKIPPED,
        "profile cleanup": Status.PASS,
    }
    assert "/docs" in results["reachable"].detail
    assert results["ready"].detail.startswith("skipped: not available")


def test_a_missing_health_endpoint_and_docs_is_a_failure() -> None:
    results = run(FakeApi(missing=("/healthz", "/docs")))

    assert results["reachable"].status is Status.FAIL


def test_an_unreachable_api_fails_and_skips_the_rest_without_crashing() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(refuse)) as c:
        results = smoke.run_smoke(c)

    assert results[0].status is Status.FAIL
    assert "ConnectError" in results[0].detail
    assert {r.status for r in results[1:]} == {Status.SKIPPED}


def test_a_failing_search_is_reported_and_the_other_checks_still_run() -> None:
    api = FakeApi(overrides={"GET /search": lambda r: json_response(500, {"detail": "boom"})})

    results = run(api)

    assert results["search"].status is Status.FAIL
    assert "500" in results["search"].detail
    assert results["profile create"].status is Status.PASS
    assert results["profile cleanup"].status is Status.PASS


@pytest.mark.parametrize(
    "body",
    [
        {"items": "x", "total_candidates": 1},
        {"items": []},
        [],
        {"items": [{"title": "x"}], "total_candidates": 1},
    ],
)
def test_a_search_answer_of_the_wrong_shape_fails(body: object) -> None:
    api = FakeApi(overrides={"GET /search": lambda r: json_response(200, body)})

    assert run(api)["search"].status is Status.FAIL


def test_a_not_ready_api_fails_the_readiness_check() -> None:
    api = FakeApi(overrides={"GET /readyz": lambda r: json_response(503, {"status": "down"})})

    assert run(api)["ready"].status is Status.FAIL


def test_without_profile_endpoints_the_profile_checks_are_skipped() -> None:
    api = FakeApi(missing=("POST /profiles",))

    results = run(api)

    assert statuses(results)["profile create"] is Status.SKIPPED
    assert {results[n].status for n in ("profile read", "match list", "match stream")} == {
        Status.SKIPPED
    }
    assert "profile cleanup" not in results
    assert "DELETE" not in " ".join(api.routes())


def test_the_smoke_profile_is_deleted_even_when_a_later_check_fails() -> None:
    api = FakeApi(
        overrides={f"GET /profiles/{PROFILE_ID}/matches": lambda r: json_response(500, {})}
    )

    results = run(api)

    assert results["match list"].status is Status.FAIL
    assert results["profile cleanup"].status is Status.PASS
    assert f"DELETE /profiles/{PROFILE_ID}" in api.routes()


def test_the_smoke_profile_is_unique_per_run_and_clearly_marked() -> None:
    api = FakeApi()
    run(api)
    run(api)

    names = [
        json.loads(r.content)["name"]
        for r in api.requests
        if r.method == "POST" and r.url.path == "/profiles"
    ]
    assert len(set(names)) == 2
    assert all(name.startswith("smoke-") for name in names)


def test_an_api_that_needs_a_token_is_skipped_without_one_and_passes_with_it() -> None:
    api = FakeApi(require_token=SECRET)

    without = run(api)
    with_token = run(FakeApi(require_token=SECRET), token=SECRET)

    assert statuses(without)["search"] is Status.SKIPPED
    assert "authentication required" in without["search"].detail
    assert statuses(without)["profile create"] is Status.SKIPPED
    assert set(statuses(with_token).values()) == {Status.PASS}


def test_a_rejected_token_is_a_failure() -> None:
    api = FakeApi(require_token="other")

    results = run(api, token=SECRET)

    assert results["search"].status is Status.FAIL
    assert "rejected" in results["search"].detail


def test_the_summary_counts_each_status() -> None:
    results = [
        smoke.passed("a", ""),
        smoke.passed("b", ""),
        smoke.failed("c", ""),
        smoke.skipped("d", "x"),
    ]

    assert smoke.summary_line(results) == "smoke FAILED: 2 passed, 1 failed, 1 skipped"
    assert smoke.summary_line(results[:2]) == "smoke OK: 2 passed, 0 failed, 0 skipped"


def test_main_prints_a_report_and_exits_zero_when_nothing_failed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = smoke.main([], transport=httpx.MockTransport(FakeApi(missing=("/readyz",))))

    out = capsys.readouterr().out
    assert code == 0
    assert "[PASS   ] reachable" in out
    assert "[SKIPPED] ready: skipped: not available" in out
    assert out.strip().splitlines()[-1] == "smoke OK: 7 passed, 0 failed, 1 skipped"


def test_main_exits_one_when_a_check_failed(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApi(overrides={"GET /search": lambda r: json_response(500, {})})

    code = smoke.main([], transport=httpx.MockTransport(api))

    assert code == 1
    assert "smoke FAILED" in capsys.readouterr().out


def test_main_never_prints_the_token(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(smoke.TOKEN_ENV, SECRET)
    api = FakeApi(
        require_token="other", overrides={"GET /search": lambda r: json_response(500, SECRET)}
    )

    code = smoke.main(["--token", SECRET], transport=httpx.MockTransport(api))

    captured = capsys.readouterr()
    assert code == 1
    assert SECRET not in captured.out + captured.err
    assert all(r.headers.get("authorization") == f"Bearer {SECRET}" for r in api.requests)


def test_main_takes_the_token_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(smoke.TOKEN_ENV, SECRET)
    api = FakeApi(require_token=SECRET)

    assert smoke.main([], transport=httpx.MockTransport(api)) == 0


@pytest.mark.parametrize("url", ["https://sanket.example.com", "http://10.0.0.5:8000"])
def test_main_refuses_a_base_url_that_is_not_local(
    url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeApi()

    code = smoke.main(["--base-url", url], transport=httpx.MockTransport(api))

    assert code == smoke.EXIT_USAGE
    assert api.requests == []
    assert "not a local address" in capsys.readouterr().out


def test_a_remote_base_url_is_allowed_on_request() -> None:
    api = FakeApi()

    code = smoke.main(
        ["--base-url", "https://staging.example.com", "--allow-remote"],
        transport=httpx.MockTransport(api),
    )

    assert code == 0
    assert api.requests[0].url.host == "staging.example.com"


def test_main_uses_the_base_url_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMOKE_BASE_URL", "http://localhost:9999")
    api = FakeApi()

    smoke.main([], transport=httpx.MockTransport(api))

    assert api.requests[0].url.port == 9999


def test_with_stream_tokens_the_stream_is_opened_with_the_token_and_without_the_bearer_header() -> (
    None
):
    api = FakeApi(require_token=SECRET, stream_token="stream-token-value")

    results = run(api, token=SECRET)

    assert set(statuses(results).values()) == {Status.PASS}
    assert "stream token" in results["match stream"].detail
    opened = [r for r in api.requests if r.url.path.endswith("/matches/stream")]
    assert len(opened) == 1
    assert "authorization" not in opened[0].headers
    assert opened[0].url.params["stream_token"] == "stream-token-value"
    minted = [r for r in api.requests if r.url.path == "/auth/stream-token"]
    assert minted[0].headers["authorization"] == f"Bearer {SECRET}"
    assert json.loads(minted[0].content) == {"profile_id": PROFILE_ID}


def test_without_stream_tokens_the_stream_is_opened_with_the_bearer_header() -> None:
    api = FakeApi(require_token=SECRET, missing=("/auth/stream-token",))

    results = run(api, token=SECRET)

    assert results["match stream"].status is Status.PASS
    assert "bearer header" in results["match stream"].detail
    opened = [r for r in api.requests if r.url.path.endswith("/matches/stream")]
    assert opened[0].headers["authorization"] == f"Bearer {SECRET}"


def test_a_stream_token_the_server_refuses_fails_the_stream_check() -> None:
    api = FakeApi(stream_token="stream-token-value")
    api.accepted_stream_token = "another-value"  # the mint endpoint and the stream disagree

    results = run(api, token=SECRET)

    assert results["match stream"].status is Status.FAIL
    assert "rejected" in results["match stream"].detail


def test_the_stream_token_is_never_printed(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApi(require_token=SECRET, stream_token="stream-token-value")

    smoke.main(["--token", SECRET], transport=httpx.MockTransport(api))

    out = capsys.readouterr().out
    assert "stream-token-value" not in out and SECRET not in out
