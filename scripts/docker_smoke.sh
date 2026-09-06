#!/bin/sh
set -eu
base="${EZII_URL:-http://127.0.0.1:8080}"
suffix="$$"
work_id="";japanese_id="";connection_id=""
cleanup(){
  [ -z "$work_id" ] || curl --silent -X DELETE "$base/api/v1/knowledge-bases/$work_id?confirm=true" >/dev/null || true
  [ -z "$japanese_id" ] || curl --silent -X DELETE "$base/api/v1/knowledge-bases/$japanese_id?confirm=true" >/dev/null || true
  [ -z "$connection_id" ] || curl --silent -X DELETE "$base/api/v1/settings/connections/$connection_id" >/dev/null || true
  docker compose --profile test stop mock-llm >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker compose --profile test up -d --force-recreate mock-llm >/dev/null
for attempt in 1 2 3 4 5 6 7 8 9 10;do curl --fail --silent http://127.0.0.1:12345/v1/models >/dev/null 2>&1&&break;sleep 1;done
curl --fail --silent "$base/api/v1/health" >/dev/null

work="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases" -H 'Content-Type: application/json' -d "{\"name\":\"Smoke Work $suffix\",\"publication_mode\":\"automatic\",\"is_default\":false}")"
japanese="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases" -H 'Content-Type: application/json' -d "{\"name\":\"Smoke Japanese $suffix\",\"publication_mode\":\"manual\",\"is_default\":false}")"
work_id="$(printf '%s' "$work" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
japanese_id="$(printf '%s' "$japanese" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
test "$(curl --silent -o /dev/null -w '%{http_code}' -X POST "$base/api/v1/knowledge-bases" -H 'Content-Type: application/json' -d "{\"name\":\"smoke work $suffix\"}")" = "409"

connection="$(curl --fail --silent -X POST "$base/api/v1/settings/connections" -H 'Content-Type: application/json' -d "{\"name\":\"Smoke LM Studio $suffix\",\"kind\":\"lm_studio\",\"base_url\":\"http://host.docker.internal:12345/v1\",\"api_key\":\"smoke-private-token\"}")"
connection_id="$(printf '%s' "$connection" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
test "$(printf '%s' "$connection" | python3 -c 'import json,sys;print(json.load(sys.stdin)["has_api_key"])')" = "True"
! printf '%s' "$connection" | grep -q 'smoke-private-token'
kept="$(curl --fail --silent -X PUT "$base/api/v1/settings/connections/$connection_id" -H 'Content-Type: application/json' -d "{\"name\":\"Smoke LM Studio $suffix\",\"kind\":\"lm_studio\",\"base_url\":\"http://host.docker.internal:12345/v1\",\"timeout_s\":30,\"retry_count\":2}")"
test "$(printf '%s' "$kept" | python3 -c 'import json,sys;print(json.load(sys.stdin)["has_api_key"])')" = "True"
cleared="$(curl --fail --silent -X PUT "$base/api/v1/settings/connections/$connection_id" -H 'Content-Type: application/json' -d "{\"name\":\"Smoke LM Studio $suffix\",\"kind\":\"lm_studio\",\"base_url\":\"http://host.docker.internal:12345/v1\",\"clear_api_key\":true,\"timeout_s\":30,\"retry_count\":2}")"
test "$(printf '%s' "$cleared" | python3 -c 'import json,sys;print(json.load(sys.stdin)["has_api_key"])')" = "False"
chat_model="$(curl --fail --silent -X POST "$base/api/v1/settings/models" -H 'Content-Type: application/json' -d "{\"connection_id\":\"$connection_id\",\"name\":\"Smoke chat $suffix\",\"model_id\":\"mock-chat\",\"capability\":\"chat\"}")"
embedding_model="$(curl --fail --silent -X POST "$base/api/v1/settings/models" -H 'Content-Type: application/json' -d "{\"connection_id\":\"$connection_id\",\"name\":\"Smoke embedding $suffix\",\"model_id\":\"mock-embedding\",\"capability\":\"embedding\",\"vector_size\":3}")"
chat_model_id="$(printf '%s' "$chat_model" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
embedding_model_id="$(printf '%s' "$embedding_model" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
probe="$(curl --fail --silent -X POST "$base/api/v1/settings/connections/$connection_id/test")"
test "$(printf '%s' "$probe" | python3 -c 'import json,sys;print(json.load(sys.stdin)["chat_available"])')" = "True"
test "$(printf '%s' "$probe" | python3 -c 'import json,sys;print(json.load(sys.stdin)["embedding_dimension"])')" = "3"

for kb_id in "$work_id" "$japanese_id";do curl --fail --silent -X PATCH "$base/api/v1/knowledge-bases/$kb_id" -H 'Content-Type: application/json' -d "{\"chat_model_id\":\"$chat_model_id\",\"embedding_model_id\":\"$embedding_model_id\"}" >/dev/null;done
work_source="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$work_id/sources/upload" -F 'file=@examples/work-demo.txt')"
test "$(printf '%s' "$work_source" | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')" = "approved"
duplicate_source="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$work_id/sources/upload" -F 'file=@examples/work-demo.txt')"
test "$(printf '%s' "$duplicate_source" | python3 -c 'import json,sys;print(json.load(sys.stdin)["deduplicated"])')" = "True"
test "$(curl --fail --silent "$base/api/v1/knowledge-bases/$work_id/sources" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')" = "1"
manual_source="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$japanese_id/sources/upload" -F 'file=@examples/japanese-demo.txt')"
manual_source_id="$(printf '%s' "$manual_source" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
test "$(printf '%s' "$manual_source" | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')" = "ready"
curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$japanese_id/sources/$manual_source_id/approve" >/dev/null
curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$work_id/reindex" >/dev/null
curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$japanese_id/reindex" >/dev/null
test "$(curl --fail --silent "$base/api/v1/knowledge-bases/$work_id/index-status" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["indexed_chunks_count"])')" = "1"
curl --fail --silent -X PATCH "$base/api/v1/settings/models/$embedding_model_id" -H 'Content-Type: application/json' -d '{"vector_size":4}' >/dev/null
test "$(curl --fail --silent "$base/api/v1/knowledge-bases/$work_id/index-status" | python3 -c 'import json,sys;print(json.load(sys.stdin)["reindex_required"])')" = "True"
test "$(curl --silent -o /dev/null -w '%{http_code}' -X POST "$base/api/v1/knowledge-bases/$work_id/reindex")" = "502"
curl --fail --silent -X PATCH "$base/api/v1/settings/models/$embedding_model_id" -H 'Content-Type: application/json' -d '{"vector_size":3}' >/dev/null
curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$work_id/reindex" >/dev/null
curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$japanese_id/reindex" >/dev/null

work_chat="$(curl --fail --silent -X POST "$base/api/v1/chats" -H 'Content-Type: application/json' -d "{\"title\":\"Work scoped chat\",\"knowledge_base_id\":\"$work_id\"}")"
japanese_chat="$(curl --fail --silent -X POST "$base/api/v1/chats" -H 'Content-Type: application/json' -d "{\"title\":\"Japanese scoped chat\",\"knowledge_base_id\":\"$japanese_id\"}")"
work_chat_id="$(printf '%s' "$work_chat" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
japanese_chat_id="$(printf '%s' "$japanese_chat" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
test "$(curl --silent -o /dev/null -w '%{http_code}' -X PATCH "$base/api/v1/chats/$work_chat_id" -H 'Content-Type: application/json' -d "{\"knowledge_base_id\":\"$japanese_id\"}")" = "422"

work_stream="$(curl --fail --silent -N -X POST "$base/api/v1/messages/$work_chat_id/stream" -H 'Content-Type: application/json' -H 'Accept: text/event-stream' -d '{"content":"What is the private fact?"}')"
japanese_stream="$(curl --fail --silent -N -X POST "$base/api/v1/messages/$japanese_chat_id/stream" -H 'Content-Type: application/json' -H 'Accept: text/event-stream' -d '{"content":"What is the private fact?"}')"
printf '%s' "$work_stream" | grep -q 'event: ready';printf '%s' "$work_stream" | grep -q 'WORK_ONLY_TOKEN';! printf '%s' "$work_stream" | grep -q 'JAPANESE_ONLY_TOKEN'
printf '%s' "$japanese_stream" | grep -q 'JAPANESE_ONLY_TOKEN';! printf '%s' "$japanese_stream" | grep -q 'WORK_ONLY_TOKEN';printf '%s' "$japanese_stream" | grep -q 'event: done'

glossary="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$work_id/glossaries" -H 'Content-Type: application/json' -d '{"name":"Smoke terms"}')"
glossary_id="$(printf '%s' "$glossary" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$work_id/glossaries/$glossary_id/terms" -H 'Content-Type: application/json' -d '{"term":"RAG","definition":"Retrieval augmented generation","synonyms":[]}' >/dev/null
test "$(curl --fail --silent "$base/api/v1/knowledge-bases/$work_id/glossaries/$glossary_id/terms" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')" = "1"
test "$(curl --fail --silent "$base/api/v1/knowledge-bases/$japanese_id/glossaries" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')" = "0"
curl --fail --silent -X PATCH "$base/api/v1/knowledge-bases/$work_id" -H 'Content-Type: application/json' -d '{"empty_retrieval_mode":"model_only_fallback"}' >/dev/null
docker compose --profile test stop mock-llm >/dev/null
failed_stream="$(curl --fail --silent -N -X POST "$base/api/v1/messages/$work_chat_id/stream" -H 'Content-Type: application/json' -H 'Accept: text/event-stream' -d '{"content":"provider outage check"}')"
printf '%s' "$failed_stream" | grep -q 'event: error';printf '%s' "$failed_stream" | grep -q 'provider_unavailable'
test "$(curl --fail --silent "$base/api/v1/chats/$work_chat_id" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["messages"]))')" = "2"
for route in chat manage sources glossaries diagnostics maintenance;do curl --fail --silent "$base/$route" >/dev/null;done
echo "docker smoke: ok"
