# Keycloak Themes (Minimal Risk)

This folder contains opt-in custom themes for Keycloak.

`ezii-min` is intentionally a small child theme of `keycloak.v2` that only overrides CSS.

## Enable in production

1. Ensure `docker-compose.prod.yml` mounts `./ops/keycloak/themes:/opt/keycloak/themes:ro`.
2. In Keycloak Admin Console:
   - Realm Settings -> Themes
   - Login Theme: `ezii-min`
3. Save realm settings.

## Rollback

Switch Login Theme back to `keycloak.v2` in the same menu.
