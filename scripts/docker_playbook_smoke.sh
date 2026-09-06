#!/bin/sh
set -eu
base="${EZII_URL:-http://127.0.0.1:8080}";suffix="$$";work_id="";other_id=""
cleanup(){ [ -z "$work_id" ] || curl --silent -X DELETE "$base/api/v1/knowledge-bases/$work_id?confirm=true" >/dev/null || true; [ -z "$other_id" ] || curl --silent -X DELETE "$base/api/v1/knowledge-bases/$other_id?confirm=true" >/dev/null || true; }
trap cleanup EXIT INT TERM
work="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases" -H 'Content-Type: application/json' -d "{\"name\":\"Playbook Work $suffix\",\"publication_mode\":\"automatic\"}")"
other="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases" -H 'Content-Type: application/json' -d "{\"name\":\"Playbook Other $suffix\",\"publication_mode\":\"automatic\"}")"
work_id="$(printf '%s' "$work" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
other_id="$(printf '%s' "$other" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
result="$(curl --fail --silent -X POST "$base/api/v1/knowledge-bases/$work_id/playbook/sync")"
test "$(printf '%s' "$result" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["repository"])')" = "defrixx/Product-security-playbook"
test "$(curl --fail --silent "$base/api/v1/knowledge-bases/$work_id/sources" | python3 -c 'import json,sys;rows=json.load(sys.stdin);assert rows and all(x["source_type"]=="github_playbook" for x in rows);print("ok")')" = "ok"
test "$(curl --fail --silent "$base/api/v1/knowledge-bases/$other_id/sources" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')" = "0"
echo "docker playbook smoke: ok"
