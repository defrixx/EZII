# Knowledge Assistant

Многопользовательский knowledge assistant с tenant isolation, glossary-first retrieval, ingestion документов и website snapshots, admin approval workflow и трассировкой источников.

## Что умеет проект

- Chat UI и admin UI на Next.js.
- Backend API на FastAPI.
- Tenant-aware хранение чатов, сообщений, глоссариев, документов и website snapshots.
- Retrieval из трех источников:
  - glossary
  - approved documents
  - approved website snapshots
- Жесткие runtime-режимы источников:
  - `glossary_only`
  - `glossary_documents`
  - `glossary_documents_web`
- Настраиваемое поведение при пустом retrieval:
  - `strict_fallback`
  - `model_only_fallback`
  - `clarifying_fallback`
- Ingestion pipeline для `pdf`, `md`, `txt`:
  - extraction
  - normalization
  - chunking
  - embeddings
  - sync в Qdrant
- Admin workflow:
  - upload/add URL
  - preview
  - approve
  - archive
  - reindex
  - delete
  - enable/disable in retrieval
- Response trace:
  - `knowledge_mode`
  - `source_types`
  - `document_ids`
  - `web_snapshot_ids`
  - `ranking_scores`

## Текущий retrieval pipeline

1. Нормализация запроса.
2. Glossary exact match.
3. Glossary synonym match.
4. Glossary text/semantic retrieval.
5. Document semantic retrieval по approved chunks.
6. Website snapshot retrieval по approved chunks.
7. Unified ranking.
8. Сборка prompt context по приоритету источников.
9. Генерация ответа моделью.

Приоритет ранжирования:

- glossary > documents > websites > model

## Knowledge modes

- `glossary_only`: участвует только глоссарий.
- `glossary_documents`: участвуют glossary + approved documents.
- `glossary_documents_web`: участвуют glossary + approved documents + approved website snapshots.

## Empty retrieval modes

- `strict_fallback`: вернуть фиксированный fallback-ответ без вызова модели.
- `model_only_fallback`: вызвать модель без knowledge context, явно пометив, что база знаний ничего не нашла.
- `clarifying_fallback`: вернуть уточняющий вопрос вместо псевдо-grounded ответа.

## Статусы knowledge sources

Для документов и website snapshots используются статусы:

- `draft`
- `processing`
- `approved`
- `archived`
- `failed`

В retrieval участвуют только записи со всеми условиями:

- `status = approved`
- `enabled_in_retrieval = true`

## Структура проекта

```text
.
├── backend/
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/                  # миграции БД
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py               # DI, auth deps
│   │   │   └── v1/
│   │   │       ├── admin.py          # admin API, documents/sites/provider/traces
│   │   │       ├── auth.py           # auth, oidc, register
│   │   │       ├── chats.py          # CRUD чатов
│   │   │       ├── glossary.py       # glossary CRUD/import/export
│   │   │       ├── messages.py       # message streaming, retrieval, trace
│   │   │       └── router.py
│   │   ├── core/
│   │   │   ├── config.py             # настройки приложения
│   │   │   ├── errors.py             # error envelope / handlers
│   │   │   ├── logging_utils.py      # redaction, safe logging
│   │   │   ├── rate_limit.py
│   │   │   ├── secret_crypto.py
│   │   │   └── security.py
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   └── session.py
│   │   ├── models/
│   │   │   └── models.py             # SQLAlchemy models
│   │   ├── repositories/
│   │   │   ├── admin_repository.py
│   │   │   ├── chat_repository.py
│   │   │   └── glossary_repository.py
│   │   ├── schemas/
│   │   │   ├── admin.py              # Pydantic schemas для admin/documents/sites
│   │   │   ├── chat.py
│   │   │   └── glossary.py
│   │   ├── services/
│   │   │   ├── document_service.py   # ingestion, chunking, qdrant sync
│   │   │   ├── provider_service.py   # OpenRouter-compatible provider
│   │   │   ├── retrieval_service.py  # unified retrieval/ranking/prompt building
│   │   │   ├── vector_service.py     # Qdrant adapter
│   │   │   └── web_retrieval_service.py
│   │   └── main.py                   # FastAPI app, startup, qdrant collections
│   ├── tests/                        # contract/unit tests backend
│   ├── requirements.txt
│   ├── alembic.ini
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── admin/                # admin page
│   │   │   ├── auth/                 # auth pages + callback
│   │   │   ├── chat/                 # chat page
│   │   │   ├── logout/
│   │   │   ├── register/
│   │   │   ├── globals.css
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── components/
│   │   │   ├── admin-panel.tsx       # admin UI, база знаний, provider settings
│   │   │   ├── chat-panel.tsx        # chat UI
│   │   │   ├── brand-title.tsx
│   │   │   ├── source-badges.tsx
│   │   │   ├── auth/
│   │   │   └── ui/
│   │   └── lib/
│   │       ├── api.ts
│   │       └── auth.ts
│   ├── package.json
│   └── Dockerfile
├── ops/
│   ├── keycloak/realm-import/        # realm import
│   └── nginx/                        # nginx configs
├── scripts/
│   ├── seed.py
│   ├── reindex_glossary_vectors.py
│   ├── reconcile_qdrant_index.py
│   ├── bootstrap-keycloak-local.sh
│   ├── configure-keycloak-client.sh
│   ├── check-auth-config.sh
│   └── init-dbs.sh
├── docker-compose.yml
├── docker-compose.prod.yml
└── .env.example
```

## Основные backend сущности

- `glossaries`
- `glossary_entries`
- `documents`
- `document_chunks`
- `document_ingestion_jobs`
- `provider_settings`
- `response_traces`
- `audit_logs`
- `error_logs`
- `messages`
- `chats`

## Документы и ingestion

Источник знаний хранится в `documents`.

Поддерживаемые source types:

- `upload`
- `website_snapshot`

Поддерживаемые upload-форматы:

- `pdf`
- `md`
- `txt`
- glossary import: только `csv`

Лимит upload-файла:

- `50 MB` на уровне backend
- `50 MB` на уровне nginx `client_max_body_size`
- `10 MB` на CSV import глоссария

Для documents и website snapshots можно хранить свободные теги в `metadata_json.tags`, фильтровать по ним в админке и включать/выключать источники из retrieval.

`website_snapshot` индексирует только конкретную страницу по указанному URL. Автоматического обхода всего домена или внутренних ссылок сейчас нет.

Ingestion делает:

- извлечение текста
- очистку markdown/plain/pdf шума
- нормализацию пробелов
- удаление пустых блоков
- сохранение `page` и `section` metadata
- chunking с overlap
- embeddings для каждого chunk
- запись в `document_chunks`
- запись в Qdrant payload:
  - `tenant_id`
  - `document_id`
  - `chunk_id`
  - `source_type`
  - `title`
  - `status`
  - `page`
  - `section`
  - `web_snapshot_id`
  - `domain`
  - `url`

## Основные API

### User API

- `POST /api/v1/messages/{chat_id}/stream`
- `GET /api/v1/chats`
- `POST /api/v1/chats`
- `GET /api/v1/chats/{chat_id}`
- `DELETE /api/v1/chats/{chat_id}`

### Glossary API

- `GET /api/v1/glossary`
- `POST /api/v1/glossary`
- `PATCH /api/v1/glossary/{glossary_id}`
- `DELETE /api/v1/glossary/{glossary_id}`
- `GET /api/v1/glossary/{glossary_id}/entries`
- `POST /api/v1/glossary/{glossary_id}/entries`
- `PATCH /api/v1/glossary/{glossary_id}/entries/{entry_id}`
- `DELETE /api/v1/glossary/{glossary_id}/entries/{entry_id}`
- `POST /api/v1/glossary/{glossary_id}/import`
- `POST /api/v1/glossary/{glossary_id}/import-csv`
- `GET /api/v1/glossary/{glossary_id}/export`

### Admin API

- `GET /api/v1/admin/provider`
- `PUT /api/v1/admin/provider`
- `GET /api/v1/admin/traces`
- `GET /api/v1/admin/logs`
- `GET /api/v1/admin/allowlist`
- `POST /api/v1/admin/allowlist`
- `PATCH /api/v1/admin/allowlist/{domain_id}`
- `DELETE /api/v1/admin/allowlist/{domain_id}`
- `GET /api/v1/admin/documents`
- `POST /api/v1/admin/documents/upload`
- `GET /api/v1/admin/documents/{document_id}`
- `PATCH /api/v1/admin/documents/{document_id}`
- `POST /api/v1/admin/documents/{document_id}/approve`
- `POST /api/v1/admin/documents/{document_id}/archive`
- `POST /api/v1/admin/documents/{document_id}/reindex`
- `DELETE /api/v1/admin/documents/{document_id}`
- `POST /api/v1/admin/sites`
- `GET /api/v1/admin/registrations/pending`
- `POST /api/v1/admin/registrations/{user_id}/approve`

## Response trace

Trace хранит:

- модель
- `knowledge_mode`
- `answer_mode`
- использованные glossary entry ids
- `document_ids`
- `web_snapshot_ids`
- `source_types`
- `ranking_scores`
- latency
- usage/fallback metadata

## Запуск локально

1. Создать env:

```bash
cp .env.example .env
```

2. При локальном HTTP запуске выставить:

```bash
AUTH_COOKIE_SECURE=false
```

3. Поднять стек:

```bash
docker compose up -d --build
```

4. Настроить локальный Keycloak:

```bash
./scripts/bootstrap-keycloak-local.sh
./scripts/configure-keycloak-client.sh
```

5. Применить seed:

```bash
docker compose exec -T backend python /scripts/seed.py
```

`seed.py` теперь работает как bootstrap для knowledge defaults:

- на первом запуске создает default glossary, базовый allowlist и provider defaults
- на последующих redeploy не восстанавливает удаленные дефолтные glossary/allowlist значения для уже существующего tenant

6. Проверить health:

```bash
curl http://localhost/api/v1/health
```

Основные адреса:

- UI: `http://localhost/`
- FastAPI docs: `http://localhost/api/docs`
- Keycloak admin: `http://localhost:8080`

Используемые volumes в compose:

- `pgdata`: PostgreSQL data
- `qdrant_data`: Qdrant storage
- `documents_data`: persistent storage для `data/documents`, чтобы загруженные файлы и website snapshots не терялись при пересоздании backend-контейнера

## Миграции

```bash
cd backend
alembic upgrade head
```

Ключевые миграции:

- `20260308_0001_initial.py`
- `20260309_0002_allowlist_notes.py`
- `20260309_0003_provider_show_source_tags.py`
- `20260309_0004_glossaries.py`
- `20260309_0005_glossary_single_default_constraint.py`
- `20260310_0006_provider_message_limit.py`
- `20260324_0007_documents.py`
- `20260324_0008_trace_retrieval_payload.py`
- `20260324_0009_knowledge_mode.py`
- `20260324_0010_empty_retrieval_mode.py`

## Тесты

Основные test-файлы:

- `backend/tests/test_document_ingestion_service.py`
- `backend/tests/test_documents_api_contract.py`
- `backend/tests/test_retrieval_and_logging.py`
- `backend/tests/test_messages_stream_contract.py`
- `backend/tests/test_glossary_api_contract.py`
- `backend/tests/test_admin_security.py`
- `backend/tests/test_auth_hardening.py`

Если `pytest` доступен:

```bash
cd backend
pytest
```

Быстрая синтаксическая проверка:

```bash
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m compileall backend/app backend/tests scripts
```

## Ограничение текущей реализации

На текущем этапе chat history сохраняется в БД и отображается в UI, но не подмешивается в prompt модели как отдельный conversational context. В prompt уходит только:

- текущий пользовательский запрос
- собранный retrieval context
- системные ограничения режима источников

Это важно учитывать для follow-up вопросов, которые зависят именно от предыдущих реплик, а не от knowledge base.
