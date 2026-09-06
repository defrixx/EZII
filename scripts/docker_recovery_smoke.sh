#!/bin/sh
set -eu
base="${EZII_URL:-http://127.0.0.1:8080}";suffix="$$";kb_id=""
cleanup(){ [ -z "$kb_id" ] || curl --silent -X DELETE "$base/api/v1/knowledge-bases/$kb_id?confirm=true" >/dev/null || true; }
trap cleanup EXIT INT TERM
kb="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases" -H 'Content-Type: application/json' -d "{\"name\":\"Recovery $suffix\",\"publication_mode\":\"automatic\"}")"
kb_id="$(printf '%s' "$kb"|python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
source="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$kb_id/sources/upload" -F 'file=@examples/work-demo.txt')"
source_id="$(printf '%s' "$source"|python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
job_id="$(printf '%s' "$source"|python3 -c 'import json,sys;print(json.load(sys.stdin)["job_id"])')"
docker compose exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -v ON_ERROR_STOP=1 -c \"DELETE FROM document_chunks WHERE document_id='$source_id';UPDATE documents SET status='processing' WHERE id='$source_id';UPDATE ingestion_jobs SET status='processing' WHERE id='$job_id';\"" >/dev/null
docker compose restart backend >/dev/null
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15;do curl --fail --silent "$base/api/v1/health" >/dev/null 2>&1&&break;sleep 1;done
detail="$(curl --fail --silent "$base/api/v1/knowledge-bases/$kb_id/sources/$source_id")"
test "$(printf '%s' "$detail"|python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["source"]["status"])')" = "approved"
test "$(printf '%s' "$detail"|python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d["chunks"]))')" = "1"
test "$(docker compose exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atc \"SELECT status FROM ingestion_jobs WHERE id='$job_id'\"")" = "completed"
cleanup_id="$(docker compose exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atqc \"INSERT INTO storage_cleanup_tasks(id,knowledge_base_id,status,attempts,created_at,updated_at) VALUES(gen_random_uuid(),'$kb_id','pending',0,now(),now()) RETURNING id\"")"
curl --fail --silent -X POST "$base/api/v1/maintenance/retry-cleanup?confirm=true" >/dev/null
test "$(docker compose exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atc \"SELECT status FROM storage_cleanup_tasks WHERE id='$cleanup_id'\"")" = "completed"
echo "docker recovery smoke: ok"
