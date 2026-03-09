#!/usr/bin/env bash
set -euo pipefail

REALM="${KEYCLOAK_REALM:-assistant}"
ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
CLIENT_ID="${OIDC_FRONTEND_CLIENT_ID:-assistant-frontend}"
REDIRECT_URI="${NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI:-${OIDC_FRONTEND_REDIRECT_URI:-}}"
DC="${DOCKER_COMPOSE_BIN:-docker compose}"

if [[ -z "${REDIRECT_URI}" ]]; then
  echo "NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI or OIDC_FRONTEND_REDIRECT_URI is required" >&2
  exit 1
fi

origin="$(printf '%s' "${REDIRECT_URI}" | sed -E 's#(https?://[^/]+).*#\1#')"
redirect_wildcard="${origin}/*"

kc() {
  ${DC} exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@"
}

csv_id() {
  tr -d '\r"' | tail -n 1
}

echo "Configuring Keycloak client ${CLIENT_ID} for realm ${REALM}..."
kc config credentials --server http://localhost:8080 --realm master --user "${ADMIN_USER}" --password "${ADMIN_PASS}" >/dev/null

client_uuid="$(kc get clients -r "${REALM}" -q "clientId=${CLIENT_ID}" --fields id --format csv | csv_id)"
if [[ -z "${client_uuid}" ]]; then
  echo "Client ${CLIENT_ID} not found in realm ${REALM}" >&2
  exit 1
fi

kc update "clients/${client_uuid}" -r "${REALM}" \
  -s "redirectUris=[\"${redirect_wildcard}\"]" \
  -s "webOrigins=[\"${origin}\"]" \
  >/dev/null

echo "Keycloak client ${CLIENT_ID} updated:"
echo "  redirectUris: ${redirect_wildcard}"
echo "  webOrigins: ${origin}"
