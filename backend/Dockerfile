# syntax=docker/dockerfile:1
# One image for every process type: the entrypoint picks the command (see docker/entrypoint.sh):
#   api | worker | migrate | ingest | index | match | extract | canonicalise | dlq | shell
# Build from the backend directory:  docker build -t sanket-backend backend
# No secrets are baked in: everything comes from the environment at run time.

ARG PYTHON_IMAGE=python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

# ---- build: wheels and a virtualenv, with the tools that never reach the final image ----
FROM ${PYTHON_IMAGE} AS build
ARG WITH_OTEL=false
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN if [ "$WITH_OTEL" = "true" ]; then pip install ".[otel]"; else pip install .; fi

# ---- runtime: slim, non-root, no compiler, no pip cache ----
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    ENVIRONMENT=production \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    ALEMBIC_INI_PATH=/app/alembic.ini
RUN groupadd --system --gid 10001 sanket \
    && useradd --system --uid 10001 --gid sanket --no-create-home --shell /usr/sbin/nologin sanket
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /usr/local/bin/sanket-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/sanket-entrypoint && chmod 0755 /usr/local/bin/sanket-entrypoint
USER sanket:sanket
EXPOSE 8000
# Meaningful for the api role; the compose file sets its own checks for the other roles.
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('API_PORT', '8000'), timeout=3)"
ENTRYPOINT ["sanket-entrypoint"]
CMD ["api"]
