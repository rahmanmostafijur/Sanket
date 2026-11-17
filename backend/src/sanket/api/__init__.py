"""The HTTP API. `create_app` builds the application; `python -m sanket.api` serves it."""

from sanket.api.app import create_app

__all__ = ["create_app"]
