"""OpenTelemetry tracing, optional and off by default.

Nothing here is imported at module load: the OpenTelemetry packages are an extra
(`pip install "sanket[otel]"`) and a deployment without them, or without an endpoint, runs
unchanged. `setup_tracing` instruments the FastAPI app and the SQLAlchemy engine and exports
spans over OTLP/HTTP. Health, readiness and metrics requests are not traced.
"""

import importlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from sqlalchemy import Engine

from sanket.config import Settings

logger = logging.getLogger(__name__)

EXCLUDED_URLS = "healthz,readyz,metrics"
_MODULES = {
    "trace": "opentelemetry.trace",
    "sdk_trace": "opentelemetry.sdk.trace",
    "sampling": "opentelemetry.sdk.trace.sampling",
    "export": "opentelemetry.sdk.trace.export",
    "resources": "opentelemetry.sdk.resources",
    "otlp": "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "fastapi": "opentelemetry.instrumentation.fastapi",
    "sqlalchemy": "opentelemetry.instrumentation.sqlalchemy",
}


@dataclass(frozen=True)
class OtelModules:
    modules: Mapping[str, Any]

    def __getitem__(self, name: str) -> Any:
        return self.modules[name]


def load_otel() -> OtelModules:
    """Import the OpenTelemetry packages; raises ImportError when the extra is missing."""
    return OtelModules({key: importlib.import_module(path) for key, path in _MODULES.items()})


def tracing_enabled(config: Settings) -> bool:
    return config.otel_enabled or config.otel_exporter_otlp_endpoint is not None


def setup_tracing(
    app: FastAPI,
    db_engine: Engine,
    config: Settings,
    loader: Any = load_otel,
) -> bool:
    """Start exporting traces when configured; True if tracing is on. Never raises: a broken
    tracing setup is logged and the API runs without it."""
    if not tracing_enabled(config):
        return False
    try:
        otel = loader()
        provider = _provider(otel, config)
        otel["fastapi"].FastAPIInstrumentor.instrument_app(
            app, tracer_provider=provider, excluded_urls=EXCLUDED_URLS
        )
        otel["sqlalchemy"].SQLAlchemyInstrumentor().instrument(
            engine=db_engine, tracer_provider=provider
        )
    except ImportError:
        logger.warning(
            "tracing is configured but the OpenTelemetry packages are missing: "
            'pip install "sanket[otel]"'
        )
        return False
    except Exception:
        logger.exception("tracing could not be started, continuing without it")
        return False
    logger.info("tracing enabled service=%s", config.otel_service_name)
    return True


def _provider(otel: OtelModules, config: Settings) -> Any:
    resource = otel["resources"].Resource.create({"service.name": config.otel_service_name})
    sampler = otel["sampling"].ParentBased(
        otel["sampling"].TraceIdRatioBased(config.otel_sample_ratio)
    )
    provider = otel["sdk_trace"].TracerProvider(resource=resource, sampler=sampler)
    exporter_kwargs = (
        {"endpoint": _traces_endpoint(config.otel_exporter_otlp_endpoint)}
        if config.otel_exporter_otlp_endpoint
        else {}
    )
    exporter = otel["otlp"].OTLPSpanExporter(**exporter_kwargs)
    provider.add_span_processor(otel["export"].BatchSpanProcessor(exporter))
    return provider


def _traces_endpoint(base: str) -> str:
    """OTEL_EXPORTER_OTLP_ENDPOINT is a base URL; the HTTP exporter wants the traces path."""
    stripped = base.rstrip("/")
    return stripped if stripped.endswith("/v1/traces") else f"{stripped}/v1/traces"
