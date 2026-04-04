# Contributing

Thanks for contributing.

## Ground Rules

- Keep changes scoped and reviewable.
- Preserve tenant isolation and authorization boundaries.
- Include tests for behavior changes.
- Keep user-visible text clear and in English.
- Avoid committing secrets, tokens, or credentials.

## Development Setup

1. Copy environment file:

```bash
cp .env.example .env
```

2. Start services:

```bash
docker compose up -d --build
```

3. Bootstrap auth and seed data:

```bash
./scripts/bootstrap-keycloak-local.sh
./scripts/configure-keycloak-client.sh
docker compose exec -T backend python /scripts/seed.py
```

## Verification Before PR

Run the subset relevant to your change:

```bash
cd backend && pytest
cd frontend && npm test
cd frontend && npm run lint
```

For security-sensitive changes, also run local secret/static scans where possible.

## Pull Request Requirements

- Describe what changed and why.
- Link related issues/advisories.
- Include screenshots for UI changes.
- Mention migrations, new env vars, or operational impact.
- Confirm no secrets were introduced.

## Commit Hygiene

- Use clear commit messages.
- Prefer additive or small iterative commits over broad rewrites.
- Keep generated files and lockfiles consistent with source changes.

## Security Reports

Do not file vulnerabilities as public issues. Follow [SECURITY.md](./SECURITY.md).
