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
KEYCLOAK_HOSTNAME_CFG="$(cfg KEYCLOAK_HOSTNAME)"
DEFAULT_TENANT_ID="$(cfg DEFAULT_TENANT_ID)"
KEYCLOAK_PUBLIC_URL="$(cfg NEXT_PUBLIC_KEYCLOAK_URL)"
REDIRECT_URI="$(cfg NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI)"
if [[ -z "${REDIRECT_URI}" ]]; then
  REDIRECT_URI="$(cfg OIDC_FRONTEND_REDIRECT_URI)"
fi
DC="${DOCKER_COMPOSE_BIN:-docker compose}"

if [[ -z "${REDIRECT_URI}" ]]; then
  # Fallback for production: derive redirect URI from the first configured CORS origin.
  first_origin="$(cfg CORS_ORIGINS | cut -d',' -f1 | xargs || true)"
  if [[ -n "${first_origin}" ]]; then
    REDIRECT_URI="${first_origin%/}/auth/callback"
    echo "Redirect URI not set explicitly, derived from CORS_ORIGINS: ${REDIRECT_URI}"
  else
    echo "NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI or OIDC_FRONTEND_REDIRECT_URI is required" >&2
    exit 1
  fi
fi

origin="$(printf '%s' "${REDIRECT_URI}" | sed -E 's#(https?://[^/]+).*#\1#')"
redirect_wildcard="${origin}/*"
if [[ -z "${KEYCLOAK_PUBLIC_URL}" ]] && [[ -n "${KEYCLOAK_HOSTNAME_CFG}" ]]; then
  KEYCLOAK_PUBLIC_URL="https://${KEYCLOAK_HOSTNAME_CFG}"
fi
KEYCLOAK_PUBLIC_URL="${KEYCLOAK_PUBLIC_URL%/}"

kc() {
  ${DC} exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@"
}

wait_keycloak_ready() {
  echo "Waiting for Keycloak API on keycloak:8080..."
  for _ in $(seq 1 90); do
    # First ensure TCP socket is open (does not depend on HTTP tools in container image).
    if ! ${DC} exec -T keycloak sh -lc "bash -lc 'exec 3<>/dev/tcp/127.0.0.1/8080'" >/dev/null 2>&1; then
      sleep 2
      continue
    fi
    # Then check admin auth path itself; this guarantees kcadm can proceed.
    if kc config credentials --server http://localhost:8080 --realm master --user "${ADMIN_USER}" --password "${ADMIN_PASS}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Keycloak API did not become ready in time" >&2
  ${DC} ps || true
  ${DC} logs --tail=200 keycloak || true
  return 1
}

csv_id() {
  tr -d '\r"' | tail -n 1
}

mapper_exists() {
  mapper="$1"
  kc get "clients/${client_uuid}/protocol-mappers/models" -r "${REALM}" \
    | grep -Eq "\"name\"[[:space:]]*:[[:space:]]*\"${mapper}\""
}

ensure_mapper() {
  mapper_name="$1"
  mapper_type="$2"
  mapper_config="$3"
  if mapper_exists "${mapper_name}"; then
    return 0
  fi
  set +e
  create_out="$(
    kc create "clients/${client_uuid}/protocol-mappers/models" -r "${REALM}" -f - <<EOF 2>&1 >/dev/null
{
  "name": "${mapper_name}",
  "protocol": "openid-connect",
  "protocolMapper": "${mapper_type}",
  "consentRequired": false,
  "config": ${mapper_config}
}
EOF
  )"
  status=$?
  set -e
  if [[ ${status} -ne 0 ]] && ! printf '%s' "${create_out}" | grep -Eqi "exists with same name|Conflict"; then
    echo "${create_out}" >&2
    exit 1
  fi
}

is_uuid() {
  local value="$1"
  [[ "${value}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]
}

backfill_missing_tenant_attributes() {
  if [[ -z "${DEFAULT_TENANT_ID}" ]]; then
    echo "DEFAULT_TENANT_ID is not set, skipping tenant_id backfill."
    return 0
  fi
  if ! is_uuid "${DEFAULT_TENANT_ID}"; then
    echo "DEFAULT_TENANT_ID is not a valid UUID: ${DEFAULT_TENANT_ID}" >&2
    exit 1
  fi

  local updated=0
  local user_ids
  user_ids="$(
    kc get users -r "${REALM}" --fields id --format csv \
      | tr -d '\r"' \
      | awk 'NF && $1 != "id" { print $1 }'
  )"

  while IFS= read -r user_id; do
    [[ -z "${user_id}" ]] && continue
    user_json="$(kc get "users/${user_id}" -r "${REALM}" 2>/dev/null || true)"
    if printf '%s' "${user_json}" | grep -Eq '"tenant_id"[[:space:]]*:'; then
      continue
    fi
    kc update "users/${user_id}" -r "${REALM}" -s "attributes.tenant_id=[\"${DEFAULT_TENANT_ID}\"]" >/dev/null
    updated=$((updated + 1))
  done <<< "${user_ids}"

  echo "tenant_id backfill complete: updated ${updated} user(s) with DEFAULT_TENANT_ID=${DEFAULT_TENANT_ID}"
}

backfill_missing_profile_names() {
  local updated=0
  local user_ids
  user_ids="$(
    kc get users -r "${REALM}" --fields id --format csv \
      | tr -d '\r"' \
      | awk 'NF && $1 != "id" { print $1 }'
  )"

  while IFS= read -r user_id; do
    [[ -z "${user_id}" ]] && continue
    user_json="$(kc get "users/${user_id}" -r "${REALM}" 2>/dev/null || true)"
    patch_json="$(
      printf '%s' "${user_json}" | python3 -c '
import json
import sys

user = json.load(sys.stdin)
email = (user.get("email") or user.get("username") or "").strip()
profile_name = email.split("@", 1)[0].strip() or "user"
first_name = (user.get("firstName") or "").strip()
last_name = (user.get("lastName") or "").strip()
required_actions = list(user.get("requiredActions") or [])
filtered_actions = [action for action in required_actions if action != "UPDATE_PROFILE"]
patch = {}
if not first_name:
    patch["firstName"] = profile_name
if not last_name:
    patch["lastName"] = profile_name
if filtered_actions != required_actions:
    patch["requiredActions"] = filtered_actions
print(json.dumps(patch))
'
    )"
    if [[ "${patch_json}" == "{}" ]]; then
      continue
    fi
    kc update "users/${user_id}" -r "${REALM}" -f - <<EOF >/dev/null
${patch_json}
EOF
    updated=$((updated + 1))
  done <<< "${user_ids}"

  echo "profile name backfill complete: updated ${updated} user(s)"
}

ensure_default_scope_for_client() {
  scope_name="$1"
  scope_id="$(kc get client-scopes -r "${REALM}" -q "name=${scope_name}" --fields id --format csv | csv_id)"
  if [[ -z "${scope_id}" ]]; then
    return 0
  fi
  if kc get "clients/${client_uuid}/default-client-scopes" -r "${REALM}" \
    | grep -Eq "\"id\"[[:space:]]*:[[:space:]]*\"${scope_id}\""; then
    return 0
  fi
  set +e
  update_out="$(
    kc create "clients/${client_uuid}/default-client-scopes/${scope_id}" -r "${REALM}" -n 2>&1 >/dev/null
  )"
  status=$?
  set -e
  if [[ ${status} -ne 0 ]]; then
    set +e
    update_out="$(
      kc update "clients/${client_uuid}/default-client-scopes/${scope_id}" -r "${REALM}" -n 2>&1 >/dev/null
    )"
    status=$?
    set -e
  fi
  if [[ ${status} -ne 0 ]] && ! printf '%s' "${update_out}" | grep -Eqi "exists|Conflict|No content"; then
    echo "${update_out}" >&2
    exit 1
  fi
}

ensure_optional_scope_for_client() {
  scope_name="$1"
  scope_id="$(kc get client-scopes -r "${REALM}" -q "name=${scope_name}" --fields id --format csv | csv_id)"
  if [[ -z "${scope_id}" ]]; then
    return 0
  fi
  if kc get "clients/${client_uuid}/optional-client-scopes" -r "${REALM}" \
    | grep -Eq "\"id\"[[:space:]]*:[[:space:]]*\"${scope_id}\""; then
    return 0
  fi
  set +e
  update_out="$(
    kc create "clients/${client_uuid}/optional-client-scopes/${scope_id}" -r "${REALM}" -n 2>&1 >/dev/null
  )"
  status=$?
  set -e
  if [[ ${status} -ne 0 ]]; then
    set +e
    update_out="$(
      kc update "clients/${client_uuid}/optional-client-scopes/${scope_id}" -r "${REALM}" -n 2>&1 >/dev/null
    )"
    status=$?
    set -e
  fi
  if [[ ${status} -ne 0 ]] && ! printf '%s' "${update_out}" | grep -Eqi "exists|Conflict|No content"; then
    echo "${update_out}" >&2
    exit 1
  fi
}

ensure_client_scope_exists() {
  scope_name="$1"
  scope_id="$(kc get client-scopes -r "${REALM}" -q "name=${scope_name}" --fields id --format csv | csv_id)"
  if [[ -z "${scope_id}" ]]; then
    set +e
    create_out="$(
      kc create client-scopes -r "${REALM}" -f - <<EOF 2>&1 >/dev/null
{
  "name": "${scope_name}",
  "protocol": "openid-connect"
}
EOF
    )"
    status=$?
    set -e
    if [[ ${status} -ne 0 ]] && ! printf '%s' "${create_out}" | grep -Eqi "exists|Conflict"; then
      echo "${create_out}" >&2
      exit 1
    fi
  fi
}

echo "Configuring Keycloak client ${CLIENT_ID} for realm ${REALM}..."
wait_keycloak_ready

if ! kc get "realms/${REALM}" >/dev/null 2>&1; then
  kc create realms -s "realm=${REALM}" -s "enabled=true" >/dev/null
fi

# Enforce baseline security settings on existing realms too (import may be skipped on existing realm).
kc update "realms/${REALM}" \
  -s "revokeRefreshToken=true" \
  -s "refreshTokenMaxReuse=1" \
  -s "verifyEmail=true" \
  -s "registrationAllowed=false" \
  -s "registrationEmailAsUsername=false" \
  -s "duplicateEmailsAllowed=false" \
  -s "resetPasswordAllowed=true" \
  -s "rememberMe=true" \
  -s "loginWithEmailAllowed=true" \
  -s "bruteForceProtected=true" \
  -s "failureFactor=10" \
  -s "waitIncrementSeconds=60" \
  -s "maxFailureWaitSeconds=900" \
  -s "quickLoginCheckMilliSeconds=1000" \
  -s "minimumQuickLoginWaitSeconds=60" \
  -s "maxDeltaTimeSeconds=43200" \
  -s "defaultDefaultClientScopes=[\"email\",\"roles\",\"web-origins\",\"tenant_scope\"]" \
  -s "passwordPolicy=length(12) and upperCase(1) and lowerCase(1) and digits(1) and specialChars(1)" \
  >/dev/null
if [[ -n "${KEYCLOAK_PUBLIC_URL}" ]]; then
  # Keycloak 26+ keeps frontend URL in realm attributes.
  kc update "realms/${REALM}" -s "attributes.frontendUrl=${KEYCLOAK_PUBLIC_URL}" >/dev/null
fi

client_uuid="$(kc get clients -r "${REALM}" -q "clientId=${CLIENT_ID}" --fields id --format csv | csv_id)"
if [[ -n "${client_uuid}" ]]; then
  client_protocol="$(kc get "clients/${client_uuid}" -r "${REALM}" --fields protocol --format csv | csv_id | tr '[:upper:]' '[:lower:]')"
  if [[ "${client_protocol}" != "openid-connect" ]]; then
    echo "Existing client ${CLIENT_ID} has protocol=${client_protocol}; recreating as openid-connect"
    kc delete "clients/${client_uuid}" -r "${REALM}" >/dev/null || true
    client_uuid=""
  fi
fi

if [[ -z "${client_uuid}" ]]; then
  kc create clients -r "${REALM}" -f - <<EOF >/dev/null
{
  "clientId": "${CLIENT_ID}",
  "name": "${CLIENT_ID}",
  "enabled": true,
  "publicClient": true,
  "protocol": "openid-connect",
  "standardFlowEnabled": true,
  "directAccessGrantsEnabled": false
}
EOF
  client_uuid="$(kc get clients -r "${REALM}" -q "clientId=${CLIENT_ID}" --fields id --format csv | csv_id)"
fi

if [[ -z "${client_uuid}" ]]; then
  echo "Client ${CLIENT_ID} was not created in realm ${REALM}" >&2
  exit 1
fi

kc update "clients/${client_uuid}" -r "${REALM}" \
  -s "publicClient=true" \
  -s "fullScopeAllowed=true" \
  -s "standardFlowEnabled=true" \
  -s "directAccessGrantsEnabled=false" \
  -s "redirectUris=[\"${redirect_wildcard}\"]" \
  -s "webOrigins=[\"${origin}\"]" \
  -s "defaultClientScopes=[\"email\",\"roles\",\"web-origins\"]" \
  >/dev/null

# Ensure standard OIDC scopes exist in realm and are attached after client update.
ensure_client_scope_exists "email"
ensure_client_scope_exists "roles"
ensure_client_scope_exists "web-origins"
ensure_default_scope_for_client "email"
ensure_default_scope_for_client "roles"
ensure_default_scope_for_client "web-origins"

# Ensure frontend tokens include API audience required by backend JWT validation.
ensure_mapper \
  "audience-${API_AUDIENCE}" \
  "oidc-audience-mapper" \
  "{\"included.client.audience\":\"${API_AUDIENCE}\",\"id.token.claim\":\"false\",\"access.token.claim\":\"true\"}"

# Ensure realm roles are always present in frontend tokens.
ensure_mapper \
  "realm roles explicit" \
  "oidc-usermodel-realm-role-mapper" \
  "{\"multivalued\":\"true\",\"userinfo.token.claim\":\"true\",\"id.token.claim\":\"true\",\"access.token.claim\":\"true\",\"claim.name\":\"realm_access.roles\",\"jsonType.label\":\"String\"}"

# Ensure tenant_id claim is propagated from user attribute.
ensure_mapper \
  "tenant_id_from_user_attribute" \
  "oidc-usermodel-attribute-mapper" \
  "{\"user.attribute\":\"tenant_id\",\"claim.name\":\"tenant_id\",\"jsonType.label\":\"String\",\"id.token.claim\":\"true\",\"access.token.claim\":\"true\",\"userinfo.token.claim\":\"true\"}"

backfill_missing_tenant_attributes
backfill_missing_profile_names

echo "Keycloak client ${CLIENT_ID} updated:"
echo "  redirectUris: ${redirect_wildcard}"
echo "  webOrigins: ${origin}"
echo "  audience mapper: ${API_AUDIENCE}"
echo "  realm roles mapper: explicit realm_access.roles"
echo "  tenant_id mapper: user attribute tenant_id"
if [[ -n "${KEYCLOAK_PUBLIC_URL}" ]]; then
  echo "  realm frontendUrl: ${KEYCLOAK_PUBLIC_URL}"
fi
