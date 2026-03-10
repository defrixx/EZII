# Glossary-First Assistant MVP

Production-oriented MVP web application for a single assistant with strict glossary-first retrieval, tenant-aware isolation, optional allowlisted web retrieval, and admin observability.

## 1) Architecture Overview

- Frontend: Next.js (App Router, TypeScript, Tailwind, shadcn/ui-compatible)
- Backend: FastAPI + SQLAlchemy + Alembic + Pydantic
- Data: PostgreSQL (system of record), Redis (rate limiting), Qdrant (glossary vectors)
- Auth: Keycloak OIDC/JWT
- AI provider: OpenRouter-compatible abstraction (`/chat/completions`, `/embeddings`)
- Infra: Docker Compose on single VDS with Nginx reverse proxy

Retrieval pipeline:
1. Normalize query
2. Exact glossary match
3. Synonym match
4. Vector similarity in Qdrant
5. Weighted ranking
6. Optional allowlisted web retrieval
7. Context assembly with glossary priority
8. Answer generation

Priority order: exact > synonym > semantic > web > model.

## 2) ERD Data Model

Core tables:
- `tenants`
- `users` (`tenant_id`, `role`)
- `chats` (`tenant_id`, `user_id`)
- `messages` (`tenant_id`, `chat_id`, `user_id`, `source_types[]`)
- `glossaries` (`tenant_id`, `name`, `priority`, `enabled`, `is_default`)
- `glossary_entries` (`tenant_id`, `glossary_id`, full requested schema)
- `allowlist_domains` (`tenant_id`, unique domain)
- `provider_settings` (`tenant_id`, OpenRouter-compatible params)
- `audit_logs` (`tenant_id`, `user_id`, action trail)
- `error_logs` (`tenant_id`, redacted error entries)
- `response_traces` (`tenant_id`, `user_id`, retrieval and model metadata)

All tenant-scoped entities enforce `tenant_id` filtering in repositories/services.

## 3) Folder Structure

- `backend/`: FastAPI app, service/repository layers, Alembic migration
- `frontend/`: Next.js user/admin app
- `ops/nginx/`: reverse proxy config
- `scripts/`: DB init + seed scripts
- `docker-compose.yml`: full stack orchestration
- `docker-compose.prod.yml`: production override

## 4) Implementation Plan

1. Infrastructure and service scaffolding
2. Multi-tenant relational model + migration
3. Auth/RBAC dependencies (Keycloak JWT)
4. Chat and glossary CRUD APIs
5. Retrieval + provider abstraction + web allowlist access
6. Trace/error/audit logging
7. Frontend chat/admin interfaces
8. Compose deployment and seed workflow

## 5) Backend Code

Entrypoint:
- `backend/app/main.py`

API routers:
- `backend/app/api/v1/auth.py`
- `backend/app/api/v1/chats.py`
- `backend/app/api/v1/messages.py`
- `backend/app/api/v1/glossary.py`
- `backend/app/api/v1/admin.py`

Glossary API:
- `GET /api/v1/glossary` list glossary sets for tenant
- `POST /api/v1/glossary` create glossary set
- `PATCH /api/v1/glossary/{glossary_id}` update glossary set
- `DELETE /api/v1/glossary/{glossary_id}` delete glossary set (default is protected)
- `GET /api/v1/glossary/{glossary_id}/entries` list entries in glossary
- `POST /api/v1/glossary/{glossary_id}/entries` create entry
- `PATCH /api/v1/glossary/{glossary_id}/entries/{entry_id}` update entry
- `DELETE /api/v1/glossary/{glossary_id}/entries/{entry_id}` delete entry
- `POST /api/v1/glossary/{glossary_id}/import` bulk import entries into glossary
- `GET /api/v1/glossary/{glossary_id}/export` export entries from glossary

Core services:
- `backend/app/services/retrieval_service.py`
- `backend/app/services/provider_service.py`
- `backend/app/services/vector_service.py`
- `backend/app/services/web_retrieval_service.py`

Security and controls:
- `backend/app/core/security.py`
- `backend/app/core/rate_limit.py`
- `backend/app/core/logging_utils.py`

## 6) Frontend Code

App pages:
- `frontend/src/app/chat/page.tsx`
- `frontend/src/app/admin/page.tsx`
- `frontend/src/app/auth/page.tsx`

Reusable components:
- `frontend/src/components/chat-panel.tsx`
- `frontend/src/components/admin-panel.tsx`
- `frontend/src/components/source-badges.tsx`
- `frontend/src/components/auth/auth-gate.tsx`
- `frontend/src/components/brand-title.tsx`

API client:
- `frontend/src/lib/api.ts`

## 7) Database Migrations

Migrations:
- `backend/alembic/versions/20260308_0001_initial.py`
- `backend/alembic/versions/20260309_0002_allowlist_notes.py`
- `backend/alembic/versions/20260309_0003_provider_show_source_tags.py`
- `backend/alembic/versions/20260309_0004_glossaries.py` (introduces multiple glossaries and migrates existing entries into tenant default glossary)
- `backend/alembic/versions/20260309_0005_glossary_single_default_constraint.py` (enforces single default glossary per tenant)

Run with:
```bash
cd backend
alembic upgrade head
```

## 8) Docker Compose Configuration

Stack file:
- `docker-compose.yml`

Includes:
- `postgres`
- `redis`
- `qdrant`
- `keycloak`
- `backend`
- `frontend`
- `nginx`

## 9) Seed Scripts

- SQL db bootstrap (env-driven): `scripts/init-dbs.sh`
- App seed script: `scripts/seed.py`
- Vector reindex script: `scripts/reindex_glossary_vectors.py`
- Index reconciliation script: `scripts/reconcile_qdrant_index.py`

Run seed:
```bash
docker compose exec backend python /scripts/seed.py
```

Reindex glossary vectors after glossary migration (recommended once):
```bash
docker compose exec -T backend python /scripts/reindex_glossary_vectors.py
```

Reconcile DB and Qdrant before production cutover:
```bash
docker compose exec -T backend python /scripts/reconcile_qdrant_index.py
# apply fixes
docker compose exec -T backend python /scripts/reconcile_qdrant_index.py --apply
```

Local fallback without OpenRouter key:
```bash
docker compose exec -T backend python /scripts/reindex_glossary_vectors.py
```
If provider key is missing, script generates deterministic stub embeddings (local/dev only).

## 10) Example Environment Variables

- `.env.example`

Usage:
```bash
cp .env.example .env
# set OPENROUTER_API_KEY and any deployment overrides
```
Toggle switches:
- No test-mode frontend toggles are used in production config.
- Login uses Keycloak hosted UI (`/auth`), registration uses backend endpoint `/api/v1/auth/register` (creates user in Keycloak).
- Default frontend OIDC scopes are controlled by `NEXT_PUBLIC_OIDC_SCOPES` (safe default: `openid`).
- Built-in self-hosted CAPTCHA for registration:
  - `REGISTER_ENFORCE_CAPTCHA=true`
  - `REGISTER_CAPTCHA_PROVIDER=builtin`
  - `REGISTER_BUILTIN_CAPTCHA_TTL_S=180`
- External CAPTCHA providers are still supported:
  - `REGISTER_CAPTCHA_PROVIDER=turnstile|hcaptcha`
  - For Turnstile: `TURNSTILE_SECRET_KEY`
  - For hCaptcha: `HCAPTCHA_SECRET_KEY`

## 11) Deployment Instructions

1. Configure env:
```bash
cp .env.example .env
```
For local HTTP-only run (without TLS), set `AUTH_COOKIE_SECURE=false` in `.env`.

2. Build and start:
```bash
docker compose up -d --build
```
3. Bootstrap local Keycloak realm/clients/test users:
```bash
./scripts/bootstrap-keycloak-local.sh
./scripts/configure-keycloak-client.sh
```
4. Seed app data:
```bash
docker compose exec -T backend python /scripts/seed.py
```
5. Verify services:
```bash
curl http://localhost/api/v1/health
```
6. Open app:
- User/Admin UI: `http://localhost/`
- FastAPI docs: `http://localhost/api/docs`
- Keycloak admin: `http://localhost:8080` (credentials from compose env)
- Local smoke users (created by bootstrap script): `smoke_admin` / `StrongPass123!`, `smoke_user` / `StrongPass123!`

Production run on VDS:
```bash
# infrastructure first
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d postgres redis qdrant keycloak
# reconcile postgres role password with current deploy secret value
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  psql -U postgres -d postgres -c "ALTER ROLE app WITH PASSWORD '<POSTGRES_PASSWORD>';"
# app services
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build backend frontend nginx
./scripts/configure-keycloak-client.sh
docker compose exec -T backend python /scripts/seed.py
docker compose exec -T backend python /scripts/reconcile_qdrant_index.py --apply
```

Keycloak realm bootstrap:
- Realm import file: `ops/keycloak/realm-import/assistant-realm.json`
- Imported automatically in prod override via `--import-realm`
- Runtime realm/client values should match `.env` (for this deployment: `KEYCLOAK_REALM=ezii`, `OIDC_FRONTEND_CLIENT_ID=ezii-frontend`)

TLS/HTTPS notes:
- Prod nginx config: `ops/nginx/nginx.prod.conf`
- Expects certs at `/etc/letsencrypt/live/app/fullchain.pem` and `/etc/letsencrypt/live/app/privkey.pem`
- Keycloak is routed through nginx by host `auth.ezii.ru`; container port is bound only on loopback (`127.0.0.1:18080`)
- Before first HTTPS start, issue certs (example with certbot on host):
```bash
sudo certbot certonly --standalone -d <YOUR_DOMAIN> -d auth.<YOUR_DOMAIN> --non-interactive --agree-tos -m <YOUR_EMAIL>
sudo ln -sfn /etc/letsencrypt/live/<YOUR_DOMAIN> /etc/letsencrypt/live/app
```

## GitHub Actions Secrets for Auto-Deploy

Workflow file:
- `.github/workflows/ci-cd.yml`
- `.github/workflows/deploy.yml` (manual deploy only)

`ci-cd.yml` flow:
- on `push`/`pull_request` to `main` runs test stage
- deploy stage runs only for `push` to `main` and only if test stage passed

Deploy step writes `.env` from GitHub Secrets, then runs:
- `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d postgres redis qdrant keycloak`
- `ALTER ROLE <POSTGRES_USER> WITH PASSWORD <POSTGRES_PASSWORD>` (sync with current secret)
- `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build backend frontend nginx`
- `./scripts/configure-keycloak-client.sh`
- `docker compose exec -T backend python /scripts/seed.py`

Required GitHub Secrets (`Settings -> Secrets and variables -> Actions -> Secrets`):
- `VDS_HOST`
- `VDS_PORT`
- `VDS_USER`
- `VDS_SSH_KEY`
- `VDS_DEPLOY_PATH`
- `VDS_GIT_PAT` (needed for first clone on VDS if repo is private)
- `DEPLOY_ENV_FILE` (multiline base `.env` template for production)
- `OPENROUTER_API_KEY`
- `POSTGRES_PASSWORD`
- `KEYCLOAK_ADMIN_USER`
- `KEYCLOAK_ADMIN_PASSWORD`

Recommended GitHub Variables (non-sensitive defaults):
- none required

Manual run:
1. Open `Actions -> Deploy to VDS`
2. Click `Run workflow`
3. Optionally set `ref` (default: `main`)

Recommended GitHub branch protection for `main`:
1. Require pull request before merging
2. Require status checks to pass
3. Select check: `CI/CD Production / test`

## 12) Production Hardening Notes

- No dev-auth shortcuts are present in production code path
- Restrict `CORS_ORIGINS` to your production domains only
- Keep auth session in HttpOnly cookies (BFF pattern), not browser-accessible tokens
- Enforce CSRF token + Origin/Referer checks on cookie-based auth mutations (`/auth/oidc/refresh`, `/auth/logout`)
- Revoke Keycloak refresh/session tokens server-side during logout (not only local cookie cleanup)
- Force HTTPS/TLS at reverse proxy and secure cookies
- Rotate provider/API secrets from a vault, not `.env`
- Add Keycloak realm/client bootstrap automation and role mapping tests
- Add DB row-level security for defense-in-depth tenant boundaries
- Add async queue for bulk glossary import + vector indexing retries
- Add stricter egress controls for web retrieval and request size/time limits
- Add integration tests for tenant isolation and glossary-priority conflicts
- Add SIEM integration for audit/error logs and retention policies
