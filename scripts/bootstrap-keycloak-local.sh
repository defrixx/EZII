#!/usr/bin/env bash
set -euo pipefail

REALM="${KEYCLOAK_REALM:-ezii}"
ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
API_CLIENT_ID="${KEYCLOAK_AUDIENCE:-assistant-api}"
FRONTEND_CLIENT_ID="${OIDC_FRONTEND_CLIENT_ID:-ezii-frontend}"
TENANT_ID="${BOOTSTRAP_TENANT_ID:-00000000-0000-0000-0000-000000000001}"
SMOKE_PASSWORD="${SMOKE_PASSWORD:-StrongPass123!}"
DC="${DOCKER_COMPOSE_BIN:-docker compose}"

kc() {
  ${DC} exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@"
}

csv_id() {
  tr -d '\r"' | tail -n 1
}

ensure_role() {
  local role_name="$1"
  if ! kc get "roles/${role_name}" -r "${REALM}" >/dev/null 2>&1; then
    kc create roles -r "${REALM}" -s "name=${role_name}" >/dev/null
  fi
}

ensure_mapper() {
  local client_uuid="$1"
  local mapper_name="$2"
  local mapper_type="$3"
  local mapper_config="$4"
  local current
  current="$(kc get "clients/${client_uuid}/protocol-mappers/models" -r "${REALM}" 2>/dev/null || true)"
  if echo "${current}" | grep -Fq "\"name\" : \"${mapper_name}\""; then
    return 0
  fi

  local create_out
  if ! create_out="$(
    kc create "clients/${client_uuid}/protocol-mappers/models" -r "${REALM}" -f - 2>&1 <<EOF
{
  "name": "${mapper_name}",
  "protocol": "openid-connect",
  "protocolMapper": "${mapper_type}",
  "consentRequired": false,
  "config": ${mapper_config}
}
EOF
  )"; then
    if echo "${create_out}" | grep -qi "exists with same name"; then
      return 0
    fi
    echo "${create_out}" >&2
    return 1
  fi
}

echo "Bootstrapping Keycloak realm ${REALM}..."
kc config credentials --server http://localhost:8080 --realm master --user "${ADMIN_USER}" --password "${ADMIN_PASS}" >/dev/null

if ! kc get "realms/${REALM}" >/dev/null 2>&1; then
  kc create realms -s "realm=${REALM}" -s "enabled=true" >/dev/null
fi

# Align local realm with secure production baseline.
kc update "realms/${REALM}" \
  -s revokeRefreshToken=true \
  -s refreshTokenMaxReuse=0 \
  -s accessTokenLifespan=300 \
  -s ssoSessionIdleTimeout=1800 \
  -s ssoSessionMaxLifespan=36000 \
  -s sslRequired=external \
  -s verifyEmail=true \
  -s registrationAllowed=false \
  -s registrationEmailAsUsername=false \
  -s duplicateEmailsAllowed=false \
  -s resetPasswordAllowed=true \
  -s rememberMe=true \
  -s loginWithEmailAllowed=true \
  -s bruteForceProtected=true \
  -s failureFactor=10 \
  -s waitIncrementSeconds=60 \
  -s maxFailureWaitSeconds=900 \
  -s quickLoginCheckMilliSeconds=1000 \
  -s minimumQuickLoginWaitSeconds=60 \
  -s maxDeltaTimeSeconds=43200 \
  -s eventsEnabled=true \
  -s adminEventsEnabled=true \
  -s adminEventsDetailsEnabled=true \
  >/dev/null

ensure_role "admin"
ensure_role "user"

api_client_id="$(kc get clients -r "${REALM}" -q clientId="${API_CLIENT_ID}" --fields id --format csv | csv_id)"
if [[ -z "${api_client_id}" ]]; then
  kc create clients -r "${REALM}" -f - <<EOF >/dev/null
{
  "clientId": "${API_CLIENT_ID}",
  "name": "${API_CLIENT_ID}",
  "enabled": true,
  "publicClient": false,
  "bearerOnly": true,
  "protocol": "openid-connect",
  "standardFlowEnabled": false,
  "directAccessGrantsEnabled": false
}
EOF
  api_client_id="$(kc get clients -r "${REALM}" -q clientId="${API_CLIENT_ID}" --fields id --format csv | csv_id)"
fi

# Keep API client non-public and bearer-only in local bootstrap too.
kc update "clients/${api_client_id}" -r "${REALM}" \
  -s publicClient=false \
  -s bearerOnly=true \
  -s standardFlowEnabled=false \
  -s directAccessGrantsEnabled=false \
  >/dev/null

frontend_client_id="$(kc get clients -r "${REALM}" -q clientId="${FRONTEND_CLIENT_ID}" --fields id --format csv | csv_id)"
if [[ -z "${frontend_client_id}" ]]; then
  kc create clients -r "${REALM}" -f - <<EOF >/dev/null
{
  "clientId": "${FRONTEND_CLIENT_ID}",
  "name": "${FRONTEND_CLIENT_ID}",
  "enabled": true,
  "publicClient": true,
  "protocol": "openid-connect",
  "standardFlowEnabled": true,
  "directAccessGrantsEnabled": false,
  "redirectUris": ["http://localhost/*", "http://127.0.0.1/*"],
  "webOrigins": ["http://localhost", "http://127.0.0.1"]
}
EOF
  frontend_client_id="$(kc get clients -r "${REALM}" -q clientId="${FRONTEND_CLIENT_ID}" --fields id --format csv | csv_id)"
fi

# Enforce secure OAuth settings even if client already existed.
kc update "clients/${frontend_client_id}" -r "${REALM}" \
  -s publicClient=true \
  -s standardFlowEnabled=true \
  -s directAccessGrantsEnabled=false \
  >/dev/null

aud_cfg="{\"included.client.audience\":\"${API_CLIENT_ID}\",\"id.token.claim\":\"false\",\"access.token.claim\":\"true\"}"
tenant_cfg="{\"claim.name\":\"tenant_id\",\"claim.value\":\"${TENANT_ID}\",\"jsonType.label\":\"String\",\"access.token.claim\":\"true\",\"id.token.claim\":\"true\",\"userinfo.token.claim\":\"true\"}"

ensure_mapper "${api_client_id}" "audience-${API_CLIENT_ID}" "oidc-audience-mapper" "${aud_cfg}"
ensure_mapper "${api_client_id}" "tenant_id_hardcoded" "oidc-hardcoded-claim-mapper" "${tenant_cfg}"
ensure_mapper "${frontend_client_id}" "audience-${API_CLIENT_ID}" "oidc-audience-mapper" "${aud_cfg}"
ensure_mapper "${frontend_client_id}" "tenant_id_hardcoded" "oidc-hardcoded-claim-mapper" "${tenant_cfg}"

ensure_user() {
  local username="$1"
  local role="$2"
  local first_name="$3"
  local last_name="$4"
  local email="$5"

  local uid
  uid="$(kc get users -r "${REALM}" -q "username=${username}" --fields id --format csv | csv_id)"
  if [[ -z "${uid}" ]]; then
    kc create users -r "${REALM}" -s "username=${username}" -s "enabled=true" -s "email=${email}" >/dev/null
    uid="$(kc get users -r "${REALM}" -q "username=${username}" --fields id --format csv | csv_id)"
  fi

  kc update "users/${uid}" -r "${REALM}" \
    -s "enabled=true" \
    -s "emailVerified=true" \
    -s "firstName=${first_name}" \
    -s "lastName=${last_name}" \
    -s "email=${email}" >/dev/null

  kc set-password -r "${REALM}" --username "${username}" --new-password "${SMOKE_PASSWORD}" >/dev/null
  kc add-roles -r "${REALM}" --uusername "${username}" --rolename "${role}" >/dev/null 2>&1 || true
}

ensure_user "smoke_admin" "admin" "Smoke" "Admin" "smoke_admin@example.com"
ensure_user "smoke_user" "user" "Smoke" "User" "smoke_user@example.com"

echo "Keycloak bootstrap complete."
echo "Users:"
echo "  smoke_admin / ${SMOKE_PASSWORD}"
echo "  smoke_user  / ${SMOKE_PASSWORD}"
