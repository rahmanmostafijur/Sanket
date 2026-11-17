"""Serve the API: `python -m sanket.api`. Binds to API_HOST:API_PORT (default 127.0.0.1:8000)."""

import uvicorn

from sanket.api.app import create_app
from sanket.config import settings
from sanket.db import engine
from sanket.indexing.config import check_dimensions
from sanket.observability.logs import configure_logging


def main() -> None:
    configure_logging()
    check_dimensions(settings.embedding_dimensions, engine)
    # Logging is ours (JSON, request ids, our own access line), not uvicorn's.
    uvicorn.run(
        create_app(),
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
