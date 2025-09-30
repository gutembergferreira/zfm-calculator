#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${SQLALCHEMY_DATABASE_URI:-}" ]]; then
  flask db upgrade || flask init-db || true
fi
exec "$@"
