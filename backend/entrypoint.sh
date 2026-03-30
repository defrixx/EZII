#!/bin/sh
set -eu

# Refresh trust store if custom CA certs are mounted into the standard Debian path.
if [ -d "/usr/local/share/ca-certificates" ]; then
  update-ca-certificates >/dev/null 2>&1 || true
fi

exec "$@"
