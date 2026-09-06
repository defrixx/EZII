#!/bin/sh
set -eu

# Keep one randomly generated encryption key in a Docker volume. An explicitly
# configured key always wins, which also makes backup/restore deterministic.
if [ -z "${PROVIDER_API_KEY_ENCRYPTION_KEY:-}" ]; then
  key_file=/app/data/secrets/provider-key
  mkdir -p "$(dirname "$key_file")"
  if [ ! -s "$key_file" ]; then
    python -c 'from cryptography.fernet import Fernet; from pathlib import Path; Path("/app/data/secrets/provider-key").write_bytes(Fernet.generate_key())'
    chmod 600 "$key_file"
  fi
  PROVIDER_API_KEY_ENCRYPTION_KEY="$(cat "$key_file")"
  export PROVIDER_API_KEY_ENCRYPTION_KEY
fi

# Refresh trust store if custom CA certs are mounted into the standard Debian path.
if [ -d "/usr/local/share/ca-certificates" ]; then
  update-ca-certificates >/dev/null 2>&1 || true
fi

alembic upgrade head
exec "$@"
