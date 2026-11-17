"""Server-Sent Events framing (https://html.spec.whatwg.org/multipage/server-sent-events.html)."""

MEDIA_TYPE = "text/event-stream"


def event_frame(event_id: int, event: str, data: str) -> str:
    """One event. `data` must be a single line (compact JSON is)."""
    if "\n" in data or "\r" in data:
        raise ValueError("SSE data must not contain a line break")
    return f"id: {event_id}\nevent: {event}\ndata: {data}\n\n"


def comment_frame(text: str) -> str:
    """A comment line: ignored by clients, keeps the connection from idling out."""
    return f": {text}\n\n"


def id_frame(event_id: int) -> str:
    """Moves the client's Last-Event-ID forward without delivering an event."""
    return f"id: {event_id}\n\n"


def retry_frame(milliseconds: int) -> str:
    return f"retry: {milliseconds}\n\n"
