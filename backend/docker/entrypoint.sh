#!/bin/sh
# Pick the process to run from the first argument. Anything else runs as given.
set -eu

role="${1:-api}"
[ "$#" -gt 0 ] && shift

case "$role" in
  api)          exec python -m sanket.api "$@" ;;
  worker)       exec python -m sanket.worker "$@" ;;
  migrate)      exec alembic upgrade head "$@" ;;
  ingest)       exec python -m sanket.ingest "$@" ;;
  index)        exec python -m sanket.indexing "$@" ;;
  match)        exec python -m sanket.matching "$@" ;;
  extract)      exec python -m sanket.extraction.runner "$@" ;;
  canonicalise) exec python -m sanket.canonicalise "$@" ;;
  backfill)     exec python -m sanket.backfill_normalized "$@" ;;
  dlq)          exec python -m sanket.queue.dlq "$@" ;;
  shell)        exec sh "$@" ;;
  *)            exec "$role" "$@" ;;
esac
