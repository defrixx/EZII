# EZII Knowledge

EZII Knowledge is a private, single-user knowledge system for a local computer. It keeps multiple knowledge bases, documents, website snapshots, glossaries, and chats isolated from one another. It can also import the Product Security playbooks maintained in `defrixx/Product-security-playbook`.

The interface is available in Russian and English and supports light, dark, and system themes.

> EZII intentionally has no authentication. Nginx publishes it only on `127.0.0.1`. Do not change this binding to `0.0.0.0`, expose the port through a router, or deploy the application on the public internet.

## Requirements

- Docker Desktop or Docker Engine with Docker Compose
- Optional: LM Studio for local chat or embedding models
- Optional: an OpenRouter API key or credentials for another OpenAI-compatible provider

## Quick start

The standard local setup does not require a `.env` file:

```bash
docker compose up --build -d
```

Open <http://127.0.0.1:8080>. On the first run:

1. Open **Manage** and create a knowledge base.
2. Create an OpenRouter, LM Studio, or OpenAI-compatible connection.
3. Add separate chat and embedding model endpoints.
4. Assign both models to the knowledge base.
5. Upload sources or use the dedicated **Recommended playbooks** section.
6. Create a chat and select its knowledge base.

Useful commands:

```bash
docker compose ps
docker compose logs -f
docker compose down
```

Production containers use `restart: unless-stopped`, so they recover after a failure or Docker restart. Containers stopped with `docker compose down` remain stopped.

## Model providers

Chat generation and embeddings are configured independently. For example, OpenRouter can generate answers while LM Studio creates embeddings locally.

- **OpenRouter:** `https://openrouter.ai/api/v1`; an API key is required.
- **LM Studio:** `http://host.docker.internal:1234/v1` from the backend container; an API key is normally unnecessary.
- **Other OpenAI-compatible APIs:** use the provider's HTTPS URL and API key when required.

For LM Studio, load the required models and start Local Server before testing the connection. Reindex every affected knowledge base after changing an embedding model or its vector dimension.

Connection testing sends small chat and embedding requests. A paid cloud provider may charge a minimal amount for these probes.

Provider API keys are encrypted before storage. The encryption key is generated automatically in the `secrets_data` Docker volume, which must be backed up together with PostgreSQL.

## Knowledge-base rules

- A chat is permanently linked to exactly one knowledge base.
- Retrieval never searches multiple knowledge bases at once.
- Sources and glossary terms from other knowledge bases cannot enter an answer.
- Source publication can be automatic or require manual approval.
- Product Security playbooks are imported only into the explicitly selected knowledge base.
- Deleting a knowledge base requires confirmation and removes its related data.

Supported sources are TXT, Markdown, PDF, HTTPS website snapshots, and Markdown files from Product Security Playbook. The default upload limit is 50 MiB.

## Recommended Product Security playbooks

The **Manage → Recommended playbooks** section offers the public `defrixx/Product-security-playbook` repository authored by **defrixx**. Select a Product Security knowledge base and start the import. Every sync is scoped to that selected base; no other knowledge base is modified.

## Optional environment overrides

Docker Compose includes defaults suitable for local use. If an override is necessary, create a private `.env` file containing only the values you need:

```dotenv
# Upload limits and document chunking.
DOCUMENT_UPLOAD_MAX_BYTES=52428800
WEBSITE_SNAPSHOT_MAX_BYTES=10485760
DOCUMENT_CHUNK_SIZE_CHARS=900
DOCUMENT_CHUNK_OVERLAP_CHARS=250

# Additional trusted local LM Studio hosts, separated by commas.
LOCAL_MODEL_HOSTS=host.docker.internal,localhost,127.0.0.1,::1

# Usually omit this so a persistent key is generated in secrets_data.
# PROVIDER_API_KEY_ENCRYPTION_KEY=<Fernet key>
```

`POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` may also be overridden, although this is normally unnecessary. Changing them after PostgreSQL has initialized requires a full volume reset or a manual database migration.

Never commit `.env`; it is ignored by Git.

## Storage and complete reset

Persistent data is stored in four Docker volumes:

- `pgdata` — settings, chats, and metadata
- `qdrant_data` — vector indexes
- `documents_data` — uploaded source files
- `secrets_data` — the key used to encrypt provider credentials

Actual names normally include the Compose project prefix, for example `ezii_pgdata`.

To permanently remove all application data and start clean:

```bash
docker compose down -v --remove-orphans
docker compose up --build -d
```

## Backup and restore

Stop writes and back up all four volumes as one consistent set. Do not restore PostgreSQL without the matching `secrets_data` volume, or stored API keys cannot be decrypted.

After restoring, verify readiness:

```bash
curl --fail http://127.0.0.1:8080/ready
```

Then open the knowledge bases, inspect their sources, and run a test retrieval. Interrupted uploads resume when the backend starts. Retriable deletion leftovers are shown with a clear explanation under **Maintenance**.

## Verification

Build the backend before running its test suite:

```bash
docker compose build backend
docker run --rm --entrypoint sh \
  -v "$PWD/backend/tests:/app/tests" \
  ezii-backend \
  -c 'pip install -q pytest && python -m pytest -q'
```

Frontend tests, ESLint, TypeScript checks, and the production build run inside the frontend image build:

```bash
docker compose build frontend
```

Integration scenarios:

```bash
./scripts/docker_smoke.sh
./scripts/docker_recovery_smoke.sh
./scripts/docker_playbook_smoke.sh
```

The playbook scenario requires GitHub access. Smoke tests create temporary application data; perform a complete volume reset afterward if you want an empty installation.

Dependency audits:

```bash
docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine npm audit
docker run --rm -v "$PWD/backend:/audit" -w /audit python:3.12-slim \
  sh -c 'pip install -q pip-audit && pip-audit -r requirements.txt'
```

## Security and diagnostics

The backend rejects non-local `Host` values and cross-site state-changing requests. Cloud provider URLs require HTTPS, while LM Studio is restricted to explicitly trusted local targets. Provider secrets, complete prompts, and document contents are not written to technical logs.

Dependency readiness is available at <http://127.0.0.1:8080/ready>. Retrieval and generation failures appear under **Diagnostics**. Interrupted operations and safe cleanup recovery are shown under **Maintenance**.
