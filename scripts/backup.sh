#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then echo "Usage: $0 BACKUP_DIRECTORY" >&2; exit 2; fi
base=$1
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$base/ezii-$stamp"
mkdir -p "$target"

cleanup() { docker compose start postgres qdrant backend frontend nginx >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

docker compose stop nginx frontend backend qdrant >/dev/null
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-app}" -Fc > "$target/postgres.dump"
docker compose stop postgres >/dev/null

for service in postgres qdrant backend; do
  container=$(docker compose ps -aq "$service")
  [ -n "$container" ] || { echo "Missing container for $service" >&2; exit 1; }
  case "$service" in
    postgres) paths="/var/lib/postgresql/data" ;;
    qdrant) paths="/qdrant/storage" ;;
    backend) paths="/app/data/documents /app/data/secrets" ;;
  esac
  docker run --rm --volumes-from "$container" -v "$target:/backup" alpine:3.22 tar -czf "/backup/$service-volumes.tar.gz" $paths
done
(cd "$target" && shasum -a 256 ./* > SHA256SUMS)
printf 'EZII backup created: %s\n' "$target"
