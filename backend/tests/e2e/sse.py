"""A streaming client for the SSE endpoint that talks to the ASGI app directly.

`TestClient` and `httpx.ASGITransport` collect a whole response before returning it, so they
cannot read a live stream. This calls the app as a server would: the request goes in, the
response messages are read from a queue as the app sends them, and closing the connection
sends the disconnect the server would send. Run it inside one event loop with the pipeline
steps, which are blocking calls (a published event waits in the subscription until the loop
runs again).
"""

import asyncio
import json
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

WAIT = 3.0
# How long "nothing arrives" is observed for. Events are already in the subscription when the
# pipeline returns, so this only has to outlast a few loop turns, not a network.
QUIET_WINDOW = 0.3

Message = MutableMapping[str, Any]


def fields_of(frame: str) -> dict[str, str]:
    """The fields of one SSE frame ("id", "event", "data"; a comment has the key ":")."""
    result: dict[str, str] = {}
    for line in frame.strip("\n").split("\n"):
        name, _, value = line.partition(": ")
        result[name or ":"] = value
    return result


@dataclass(frozen=True)
class MatchEvent:
    id: int
    data: dict[str, Any]


class SseConnection:
    """One open request. Create it with `open_sse`."""

    def __init__(
        self,
        status: int,
        headers: dict[str, str],
        queue: "asyncio.Queue[Message]",
        task: "asyncio.Task[None]",
        disconnect: asyncio.Event,
    ) -> None:
        self.status = status
        self.headers = headers
        self._queue = queue
        self._task = task
        self._disconnect = disconnect
        self._pending: list[bytes] = []
        self.frames: list[str] = []

    async def _next_chunk(self, timeout: float) -> bytes | None:
        """The next non-empty body chunk, or None when the response ended."""
        while not self._pending:
            message = await asyncio.wait_for(self._queue.get(), timeout)
            if message["type"] != "http.response.body":
                continue
            if message.get("body"):
                self._pending.append(message["body"])
            elif not message.get("more_body", False):
                return None
        return self._pending.pop(0)

    async def next_frame(self, timeout: float = WAIT) -> str:
        chunk = await self._next_chunk(timeout)
        if chunk is None:
            raise EOFError("the response ended")
        frame = chunk.decode("utf-8")
        self.frames.append(frame)
        return frame

    async def next_event(self, timeout: float = WAIT) -> MatchEvent:
        """The next `match` event, skipping the retry hint, bare ids and heartbeats. The timeout
        covers the whole wait, heartbeats included."""
        async with asyncio.timeout(timeout):
            while True:
                fields = fields_of(await self.next_frame(timeout))
                if fields.get("event") == "match":
                    return MatchEvent(int(fields["id"]), json.loads(fields["data"]))

    async def events(self, count: int, timeout: float = WAIT) -> list[MatchEvent]:
        return [await self.next_event(timeout) for _ in range(count)]

    async def quiet(self, window: float = QUIET_WINDOW) -> bool:
        """True when no match event arrives during `window` seconds."""
        try:
            await self.next_event(window)
        except (TimeoutError, EOFError):
            return True
        return False

    async def close(self) -> None:
        """Disconnect like a client leaving, and wait for the app to finish cleaning up."""
        self._disconnect.set()
        try:
            await asyncio.wait_for(self._task, WAIT)
        except TimeoutError:
            self._task.cancel()
            raise


async def open_sse(
    app: FastAPI,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
    query: str = "",
    timeout: float = WAIT,
) -> SseConnection:
    """Send `GET path` to the app and return once the response has started."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "scheme": "http",
        "root_path": "",
    }
    queue: asyncio.Queue[Message] = asyncio.Queue()
    disconnect = asyncio.Event()
    request_sent = False

    async def receive() -> Message:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        await queue.put(message)

    task = asyncio.create_task(app(scope, receive, send))
    start = await asyncio.wait_for(queue.get(), timeout)
    assert start["type"] == "http.response.start", start
    response_headers = {k.decode(): v.decode() for k, v in start["headers"]}
    return SseConnection(start["status"], response_headers, queue, task, disconnect)


async def open_live(app: FastAPI, profile_id: int, **kwargs: Any) -> SseConnection:
    """A fresh (no Last-Event-ID) stream, read up to the point where it is waiting for live
    events: the retry hint, the bare id frame that gives the client its cursor, and the first
    heartbeat, which shows the stream is subscribed and idle.
    (Use a short heartbeat interval in the settings so this does not wait long.)"""
    connection = await open_sse(app, f"/profiles/{profile_id}/matches/stream", **kwargs)
    assert connection.status == 200
    assert fields_of(await connection.next_frame())["retry"]
    assert set(fields_of(await connection.next_frame())) == {"id"}
    assert fields_of(await connection.next_frame()) == {":": "ping"}
    return connection
