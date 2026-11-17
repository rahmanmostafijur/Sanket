"""Builders for the authentication tests: signed tokens and API clients that require them."""

import os
import time
from typing import Any

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sanket.api import create_app
from sanket.config import Settings
from sanket.embeddings.fake import FakeEmbeddingClient
from tests.index_helpers import SPEC

SECRET = "unit-test-secret-of-at-least-32-characters"
STREAM_SECRET = "stream-test-secret-of-at-least-32-chars"
API_KEY = "api-key-for-tests-0123456789abcdef"


def token(secret: str = SECRET, algorithm: str = "HS256", **claims: Any) -> str:
    payload: dict[str, Any] = {"sub": "alice", "exp": int(time.time()) + 600, **claims}
    return jwt.encode({k: v for k, v in payload.items() if v is not None}, secret, algorithm)


def bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": os.environ["TEST_DATABASE_URL"],
        "embedding_model": SPEC.model_name,
        "embedding_model_version": SPEC.model_version,
        "embedding_dimensions": SPEC.dimensions,
        "auth_jwt_secret": SECRET,
        "gemini_api_key": None,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def auth_client(engine: Engine, **overrides: Any) -> TestClient:
    """A client for an app that needs real credentials (a JWT signed with SECRET by default)."""
    config = settings(**overrides)
    return TestClient(create_app(config, engine, FakeEmbeddingClient()))


ALICE_HEADERS = bearer(token(sub="alice"))
