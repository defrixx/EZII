#!/usr/bin/env bash
set -euo pipefail

read_env_file_var() {
  key="$1"
  if [[ ! -f ".env" ]]; then
    return 0
  fi
  grep -m1 -E "^[[:space:]]*${key}[[:space:]]*=" .env \
    | sed -E "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//" \
    || true
}

cfg() {
  key="$1"
  default="${2:-}"
  current="${!key:-}"
  if [[ -n "${current}" ]]; then
    printf '%s' "${current}"
    return 0
  fi
  from_file="$(read_env_file_var "${key}")"
  if [[ -n "${from_file}" ]]; then
    printf '%s' "${from_file}"
    return 0
  fi
  printf '%s' "${default}"
}

REALM="$(cfg KEYCLOAK_REALM ezii)"
ADMIN_USER="$(cfg KEYCLOAK_ADMIN admin)"
ADMIN_PASS="$(cfg KEYCLOAK_ADMIN_PASSWORD admin)"
CLIENT_ID="$(cfg OIDC_FRONTEND_CLIENT_ID ezii-frontend)"
API_AUDIENCE="$(cfg KEYCLOAK_AUDIENCE assistant-api)"
DEFAULT_TENANT_ID="$(cfg DEFAULT_TENANT_ID)"
AUTH_CHECK_ACCESS_TOKEN="${AUTH_CHECK_ACCESS_TOKEN:-}"
REDIRECT_URI="$(cfg NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI)"
if [[ -z "${REDIRECT_URI}" ]]; then
  REDIRECT_URI="$(cfg OIDC_FRONTEND_REDIRECT_URI)"
fi
if [[ -z "${REDIRECT_URI}" ]]; then
  first_origin="$(cfg CORS_ORIGINS | cut -d',' -f1 | xargs || true)"
  if [[ -n "${first_origin}" ]]; then
    REDIRECT_URI="${first_origin%/}/auth/callback"
  fi
fi

if [[ -z "${REDIRECT_URI}" ]]; then
  echo "FAIL: missing NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI / OIDC_FRONTEND_REDIRECT_URI / CORS_ORIGINS fallback"
  exit 2
fi

origin="$(printf '%s' "${REDIRECT_URI}" | sed -E 's#(https?://[^/]+).*#\1#')"
redirect_wildcard="${origin}/*"
DC="${DOCKER_COMPOSE_BIN:-docker compose}"

kc() {
  ${DC} exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@"
}

csv_id() {
  tr -d '\r"' | tail -n 1
}

scope_in_realm_defaults() {
  local realm_json="$1"
  local scope_name="$2"
  has_json_kv "${realm_json}" "\"defaultDefaultClientScopes\"[[:space:]]*:[[:space:]]*\\[[^]]*\"${scope_name}\""
}

fail_count=0
warn_count=0
pass_count=0

pass() {
  pass_count=$((pass_count + 1))
  echo "PASS: $1"
}

warn() {
  warn_count=$((warn_count + 1))
  echo "WARN: $1"
}

fail() {
  fail_count=$((fail_count + 1))
  echo "FAIL: $1"
}

has_json_kv() {
  local json="$1"
  local pattern="$2"
  printf '%s' "${json}" | grep -Eq "${pattern}"
}

extract_jwt_from_text() {
  text="$1"
  # Pick first JWT-looking token from arbitrary text/json payload.
  printf '%s' "${text}" | grep -Eo '[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' | head -n 1 || true
}

decode_jwt_payload_json() {
  token="$1"
  python3 - "$token" <<'PY'
import base64
import json
import sys

tok = sys.argv[1]
parts = tok.split(".")
if len(parts) != 3:
    sys.exit(2)
payload = parts[1]
payload += "=" * (-len(payload) % 4)
raw = base64.urlsafe_b64decode(payload.encode("ascii"))
obj = json.loads(raw.decode("utf-8"))
print(json.dumps(obj, ensure_ascii=False))
PY
}

echo "Checking auth configuration for realm=${REALM} client=${CLIENT_ID}..."

set +e
kc config credentials --server http://localhost:8080 --realm master --user "${ADMIN_USER}" --password "${ADMIN_PASS}" >/dev/null 2>&1
status=$?
set -e
if [[ ${status} -ne 0 ]]; then
  echo "FAIL: unable to auth with kcadm (KEYCLOAK_ADMIN/KEYCLOAK_ADMIN_PASSWORD or container readiness)"
  exit 2
fi
pass "kcadm auth successful"

if kc get "realms/${REALM}" >/dev/null 2>&1; then
  pass "realm ${REALM} exists"
else
  fail "realm ${REALM} missing"
fi

client_uuid="$(kc get clients -r "${REALM}" -q "clientId=${CLIENT_ID}" --fields id --format csv | csv_id)"
if [[ -z "${client_uuid}" ]]; then
  fail "client ${CLIENT_ID} missing in realm ${REALM}"
else
  pass "client ${CLIENT_ID} exists"
fi

realm_json="$(kc get "realms/${REALM}")"

if [[ -n "${client_uuid}" ]]; then
  client_json="$(kc get "clients/${client_uuid}" -r "${REALM}")"

  if has_json_kv "${client_json}" '"publicClient"[[:space:]]*:[[:space:]]*true'; then
    pass "client is publicClient=true"
  else
    fail "client publicClient must be true"
  fi

  if has_json_kv "${client_json}" '"standardFlowEnabled"[[:space:]]*:[[:space:]]*true'; then
    pass "client standardFlowEnabled=true"
  else
    fail "client standardFlowEnabled must be true"
  fi

  if has_json_kv "${client_json}" "\"${redirect_wildcard}\""; then
    pass "redirectUris include ${redirect_wildcard}"
  else
    fail "redirectUris missing ${redirect_wildcard}"
  fi

  if has_json_kv "${client_json}" "\"${origin}\""; then
    pass "webOrigins include ${origin}"
  else
    fail "webOrigins missing ${origin}"
  fi

  mappers_json="$(kc get "clients/${client_uuid}/protocol-mappers/models" -r "${REALM}")"

  if has_json_kv "${mappers_json}" "\"name\"[[:space:]]*:[[:space:]]*\"audience-${API_AUDIENCE}\""; then
    pass "audience mapper audience-${API_AUDIENCE} exists"
  else
    fail "audience mapper audience-${API_AUDIENCE} missing"
  fi

  if has_json_kv "${mappers_json}" '"included.client.audience"[[:space:]]*:[[:space:]]*"'${API_AUDIENCE}'"'; then
    pass "audience mapper targets ${API_AUDIENCE}"
  else
    warn "cannot confirm audience mapper target ${API_AUDIENCE}"
  fi

  if has_json_kv "${mappers_json}" '"name"[[:space:]]*:[[:space:]]*"tenant_id_from_user_attribute"'; then
    pass "tenant_id mapper exists"
  else
    if has_json_kv "${mappers_json}" '"claim.name"[[:space:]]*:[[:space:]]*"tenant_id"'; then
      pass "tenant_id claim mapper exists (non-standard name)"
    else
      fail "tenant_id mapper missing"
    fi
  fi

  for scope_name in email roles; do
    scope_id="$(kc get client-scopes -r "${REALM}" -q "name=${scope_name}" --fields id --format csv | csv_id)"
    if [[ -z "${scope_id}" ]]; then
      fail "client scope ${scope_name} missing in realm"
      continue
    fi
    attached_default=0
    attached_optional=0
    if kc get "clients/${client_uuid}/default-client-scopes" -r "${REALM}" | grep -Eq "\"id\"[[:space:]]*:[[:space:]]*\"${scope_id}\""; then
      attached_default=1
    fi
    if kc get "clients/${client_uuid}/optional-client-scopes" -r "${REALM}" | grep -Eq "\"id\"[[:space:]]*:[[:space:]]*\"${scope_id}\""; then
      attached_optional=1
    fi

    if [[ "${attached_default}" -eq 1 ]]; then
      pass "default client scope ${scope_name} attached"
    elif scope_in_realm_defaults "${realm_json}" "${scope_name}"; then
      pass "default client scope ${scope_name} inherited from realm defaults"
    elif [[ "${scope_name}" = "email" && "${attached_optional}" -eq 1 ]]; then
      pass "client scope email attached as optional"
    else
      fail "default client scope ${scope_name} not attached"
    fi
  done

  web_scope_id="$(kc get client-scopes -r "${REALM}" -q "name=web-origins" --fields id --format csv | csv_id)"
  if [[ -z "${web_scope_id}" ]]; then
    fail "client scope web-origins missing in realm"
  else
    attached_default=0
    attached_optional=0
    if kc get "clients/${client_uuid}/default-client-scopes" -r "${REALM}" | grep -Eq "\"id\"[[:space:]]*:[[:space:]]*\"${web_scope_id}\""; then
      attached_default=1
    fi
    if kc get "clients/${client_uuid}/optional-client-scopes" -r "${REALM}" | grep -Eq "\"id\"[[:space:]]*:[[:space:]]*\"${web_scope_id}\""; then
      attached_optional=1
    fi
    if [[ "${attached_default}" -eq 1 ]]; then
      pass "client scope web-origins attached as default"
    elif [[ "${attached_optional}" -eq 1 ]]; then
      pass "client scope web-origins attached as optional"
    else
      fail "client scope web-origins is not attached (default/optional)"
    fi
  fi
fi

for role_name in admin user; do
  if kc get "roles/${role_name}" -r "${REALM}" >/dev/null 2>&1; then
    pass "realm role ${role_name} exists"
  else
    fail "realm role ${role_name} missing"
  fi
done

if has_json_kv "${realm_json}" '"revokeRefreshToken"[[:space:]]*:[[:space:]]*true'; then
  if has_json_kv "${realm_json}" '"refreshTokenMaxReuse"[[:space:]]*:[[:space:]]*1'; then
    pass "refresh token rotation allows single reuse to avoid tab-race false logouts"
  elif has_json_kv "${realm_json}" '"refreshTokenMaxReuse"[[:space:]]*:[[:space:]]*0'; then
    warn "revokeRefreshToken=true and refreshTokenMaxReuse=0 can cause refresh races across tabs"
  else
    pass "refresh token reuse policy is not strict-0"
  fi
else
  pass "revokeRefreshToken=false (fewer refresh races)"
fi

# Runtime claim validation using a real (or example) access token.
runtime_access_token=""
if [[ -n "${AUTH_CHECK_ACCESS_TOKEN}" ]]; then
  runtime_access_token="${AUTH_CHECK_ACCESS_TOKEN}"
  pass "using AUTH_CHECK_ACCESS_TOKEN for runtime claim validation"
elif [[ -n "${client_uuid}" ]]; then
  set +e
  example_json="$(kc get "clients/${client_uuid}/evaluate-scopes/generate-example-access-token" -r "${REALM}" 2>/dev/null)"
  status=$?
  set -e
  if [[ ${status} -eq 0 ]]; then
    runtime_access_token="$(extract_jwt_from_text "${example_json}")"
    if [[ -n "${runtime_access_token}" ]]; then
      pass "example access token obtained from Keycloak evaluate-scopes"
    fi
  fi
fi

if [[ -n "${runtime_access_token}" ]]; then
  set +e
  payload_json="$(decode_jwt_payload_json "${runtime_access_token}" 2>/dev/null)"
  status=$?
  set -e
  if [[ ${status} -ne 0 || -z "${payload_json}" ]]; then
    fail "unable to decode runtime access token payload"
  else
    if has_json_kv "${payload_json}" '"sub"[[:space:]]*:[[:space:]]*"[^"]+"'; then
      pass "runtime token contains sub"
    else
      fail "runtime token missing sub"
    fi

    if has_json_kv "${payload_json}" '"tenant_id"[[:space:]]*:[[:space:]]*"[0-9a-fA-F-]{36}"'; then
      pass "runtime token contains tenant_id UUID"
    else
      fail "runtime token missing tenant_id UUID"
    fi

    if has_json_kv "${payload_json}" "\"aud\"[[:space:]]*:[[:space:]]*\"${API_AUDIENCE}\"" \
      || has_json_kv "${payload_json}" "\"aud\"[[:space:]]*:[[:space:]]*\\[[^]]*\"${API_AUDIENCE}\""; then
      pass "runtime token audience includes ${API_AUDIENCE}"
    else
      fail "runtime token audience missing ${API_AUDIENCE}"
    fi

    if has_json_kv "${payload_json}" '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"(user|admin)"'; then
      pass "runtime token has realm role claims"
    else
      fail "runtime token missing realm user/admin role claims"
    fi
  fi
else
  pass "runtime token claim checks skipped (no token source available in this environment)"
fi

users_json="$(kc get users -r "${REALM}" --fields id,username,attributes)"
users_without_tenant="$(python3 - <<'PY' "${users_json}"
import json
import sys

try:
    payload = json.loads(sys.argv[1])
except Exception:
    print("")
    sys.exit(0)

missing = []
for user in payload if isinstance(payload, list) else []:
    username = str(user.get("username") or "").strip()
    attrs = user.get("attributes") or {}
    tenant = attrs.get("tenant_id")
    has_tenant = False
    if isinstance(tenant, list):
        has_tenant = any(str(x).strip() for x in tenant)
    elif isinstance(tenant, str):
        has_tenant = bool(tenant.strip())
    if username and not has_tenant:
        missing.append(username)

print("\n".join(sorted(set(missing))))
PY
)"
if [[ -n "${users_without_tenant}" ]]; then
  if [[ -n "${DEFAULT_TENANT_ID}" ]]; then
    warn "users without tenant_id found (run ./scripts/configure-keycloak-client.sh to backfill)"
    printf '%s\n' "${users_without_tenant}" | sed 's/^/  - /'
  else
    warn "users without tenant_id found and DEFAULT_TENANT_ID is empty"
    printf '%s\n' "${users_without_tenant}" | sed 's/^/  - /'
  fi
else
  pass "all inspected users have tenant_id attribute"
fi

echo
echo "Summary: ${pass_count} PASS, ${warn_count} WARN, ${fail_count} FAIL"

if [[ ${fail_count} -gt 0 ]]; then
  exit 1
fi
exit 0
