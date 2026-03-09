#!/bin/bash
set -euo pipefail

APP_DB_NAME="${APP_DB_NAME:-app}"
KEYCLOAK_DB_NAME="${KEYCLOAK_DB_NAME:-keycloak}"

if ! psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname='${APP_DB_NAME}'" | grep -q 1; then
  createdb --username "$POSTGRES_USER" "$APP_DB_NAME"
fi

if ! psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname='${KEYCLOAK_DB_NAME}'" | grep -q 1; then
  createdb --username "$POSTGRES_USER" "$KEYCLOAK_DB_NAME"
fi
