#!/bin/sh
set -eu

if [ "$#" -ne 2 ] || [ "$2" != "--replace-existing-data" ]; then
  echo "Usage: $0 BACKUP_DIRECTORY --replace-existing-data" >&2
  echo "WARNING: replaces the current PostgreSQL, Qdrant, documents and secrets volumes." >&2
  exit 2
fi
backup=$1
for file in postgres-volumes.tar.gz qdrant-volumes.tar.gz backend-volumes.tar.gz SHA256SUMS; do [ -f "$backup/$file" ] || { echo "Missing $file" >&2; exit 1; }; done
(cd "$backup" && shasum -a 256 -c SHA256SUMS)
docker compose stop nginx frontend backend qdrant postgres >/dev/null
for service in postgres qdrant backend; do
  container=$(docker compose ps -aq "$service")
  case "$service" in
    postgres) archive=postgres-volumes.tar.gz; paths="/var/lib/postgresql/data" ;;
    qdrant) archive=qdrant-volumes.tar.gz; paths="/qdrant/storage" ;;
    backend) archive=backend-volumes.tar.gz; paths="/app/data/documents /app/data/secrets" ;;
  esac
  docker run --rm --volumes-from "$container" -v "$backup:/backup:ro" alpine:3.22 sh -c "rm -rf $paths && tar -xzf /backup/$archive -C /"
done
docker compose start postgres qdrant backend frontend nginx >/dev/null
echo "EZII backup restored."
