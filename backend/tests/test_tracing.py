"""Tracing hooks: off by default, a no-op without the packages, wired when they exist."""

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine

from sanket.config import Settings
from sanket.observability.tracing import (
    EXCLUDED_URLS,
    OtelModules,
    _traces_endpoint,
    setup_tracing,
    tracing_enabled,
)

URL = "postgresql+psycopg://u:p@127.0.0.1:5433/x_test"


def config(**values: Any) -> Settings:
    return Settings.model_validate({"database_url": URL, **values})


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def modules(self) -> OtelModules:
        calls = self.calls

        class Provider:
            def __init__(self, **kwargs: Any) -> None:
                calls.append(("provider", kwargs))

            def add_span_processor(self, processor: Any) -> None:
                calls.append(("processor", processor))

        class Instrumentor:
            @staticmethod
            def instrument_app(app: Any, **kwargs: Any) -> None:
                calls.append(("fastapi", kwargs))

            def instrument(self, **kwargs: Any) -> None:
                calls.append(("sqlalchemy", kwargs))

        return OtelModules(
            {
                "sdk_trace": SimpleNamespace(TracerProvider=Provider),
                "sampling": SimpleNamespace(
                    ParentBased=lambda root: ("parent", root),
                    TraceIdRatioBased=lambda ratio: ("ratio", ratio),
                ),
                "export": SimpleNamespace(BatchSpanProcessor=lambda exporter: ("batch", exporter)),
                "resources": SimpleNamespace(Resource=SimpleNamespace(create=lambda attrs: attrs)),
                "otlp": SimpleNamespace(OTLPSpanExporter=lambda **kwargs: ("otlp", kwargs)),
                "fastapi": SimpleNamespace(FastAPIInstrumentor=Instrumentor),
                "sqlalchemy": SimpleNamespace(SQLAlchemyInstrumentor=Instrumentor),
            }
        )


def test_tracing_is_off_by_default() -> None:
    assert not tracing_enabled(config())
    assert tracing_enabled(config(otel_enabled=True))
    assert tracing_enabled(config(otel_exporter_otlp_endpoint="http://collector:4318"))
    assert setup_tracing(FastAPI(), create_engine("sqlite://"), config()) is False


def test_when_enabled_the_app_and_engine_are_instrumented_and_probes_excluded() -> None:
    recorder = Recorder()
    cfg = config(otel_exporter_otlp_endpoint="http://collector:4318", otel_sample_ratio=0.25)

    started = setup_tracing(FastAPI(), create_engine("sqlite://"), cfg, loader=recorder.modules)

    by_name = {name: value for name, value in recorder.calls}
    assert started is True
    assert by_name["fastapi"]["excluded_urls"] == EXCLUDED_URLS
    assert "engine" in by_name["sqlalchemy"]
    assert by_name["provider"]["sampler"] == ("parent", ("ratio", 0.25))
    assert by_name["provider"]["resource"] == {"service.name": "sanket-api"}
    assert by_name["processor"] == (
        "batch",
        ("otlp", {"endpoint": "http://collector:4318/v1/traces"}),
    )


def test_missing_packages_are_logged_and_the_api_runs_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def missing() -> OtelModules:
        raise ImportError("no opentelemetry")

    started = setup_tracing(
        FastAPI(), create_engine("sqlite://"), config(otel_enabled=True), loader=missing
    )

    assert started is False
    assert "sanket[otel]" in caplog.text


def test_a_broken_setup_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> OtelModules:
        raise RuntimeError("bad exporter")

    caplog.set_level(logging.ERROR)

    assert (
        setup_tracing(FastAPI(), create_engine("sqlite://"), config(otel_enabled=True), broken)
        is False
    )
    assert "continuing without it" in caplog.text


def test_the_traces_path_is_added_to_a_base_endpoint_once() -> None:
    assert _traces_endpoint("http://c:4318/") == "http://c:4318/v1/traces"
    assert _traces_endpoint("http://c:4318/v1/traces") == "http://c:4318/v1/traces"
