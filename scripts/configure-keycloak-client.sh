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

REALM="$(cfg KEYCLOAK_REALM assistant)"
ADMIN_USER="$(cfg KEYCLOAK_ADMIN admin)"
ADMIN_PASS="$(cfg KEYCLOAK_ADMIN_PASSWORD admin)"
CLIENT_ID="$(cfg OIDC_FRONTEND_CLIENT_ID assistant-frontend)"
API_AUDIENCE="$(cfg KEYCLOAK_AUDIENCE assistant-api)"
KEYCLOAK_HOSTNAME_CFG="$(cfg KEYCLOAK_HOSTNAME)"
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

echo "Configuring Keycloak client ${CLIENT_ID} for realm ${REALM}..."
wait_keycloak_ready

if ! kc get "realms/${REALM}" >/dev/null 2>&1; then
  kc create realms -s "realm=${REALM}" -s "enabled=true" >/dev/null
fi

client_uuid="$(kc get clients -r "${REALM}" -q "clientId=${CLIENT_ID}" --fields id --format csv | csv_id)"
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
  -s "standardFlowEnabled=true" \
  -s "directAccessGrantsEnabled=false" \
  -s "redirectUris=[\"${redirect_wildcard}\"]" \
  -s "webOrigins=[\"${origin}\"]" \
  >/dev/null

# Ensure frontend tokens include API audience required by backend JWT validation.
mapper_name="audience-${API_AUDIENCE}"
if ! mapper_exists "${mapper_name}"; then
  kc create "clients/${client_uuid}/protocol-mappers/models" -r "${REALM}" -f - <<EOF >/dev/null
{
  "name": "${mapper_name}",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-audience-mapper",
  "consentRequired": false,
  "config": {
    "included.client.audience": "${API_AUDIENCE}",
    "id.token.claim": "false",
    "access.token.claim": "true"
  }
}
EOF
fi

# Ensure tenant_id claim is propagated from user attribute.
tenant_mapper="tenant_id_from_user_attribute"
if ! mapper_exists "${tenant_mapper}"; then
  kc create "clients/${client_uuid}/protocol-mappers/models" -r "${REALM}" -f - <<'EOF' >/dev/null
{
  "name": "tenant_id_from_user_attribute",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-usermodel-attribute-mapper",
  "consentRequired": false,
  "config": {
    "user.attribute": "tenant_id",
    "claim.name": "tenant_id",
    "jsonType.label": "String",
    "id.token.claim": "true",
    "access.token.claim": "true",
    "userinfo.token.claim": "true"
  }
}
EOF
fi

echo "Keycloak client ${CLIENT_ID} updated:"
echo "  redirectUris: ${redirect_wildcard}"
echo "  webOrigins: ${origin}"
echo "  audience mapper: ${API_AUDIENCE}"
echo "  tenant_id mapper: user attribute tenant_id"
