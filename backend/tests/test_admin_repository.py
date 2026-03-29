from sqlalchemy.dialects import postgresql

from app.repositories.admin_repository import AdminRepository


def test_list_document_tags_postgres_avoids_distinct_order_by_conflict():
    captured: dict[str, object] = {}

    class DummyDb:
        def scalars(self, stmt):
            captured["stmt"] = stmt
            return ["Security", "ops"]

    repo = AdminRepository(DummyDb())  # type: ignore[arg-type]
    repo._is_postgres = lambda: True  # type: ignore[method-assign]

    result = repo.list_document_tags(
        tenant_id="00000000-0000-0000-0000-000000000001",
        source_type="upload",
    )

    assert result == ["Security", "ops"]

    stmt = captured["stmt"]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    lower_sql = sql.lower()
    assert "select distinct" not in lower_sql
    assert "group by tag_values.value" in lower_sql
    assert "order by lower(tag_values.value)" in lower_sql


def test_search_document_chunks_text_ignores_stopwords_only_query():
    class DummyDb:
        def execute(self, stmt):  # pragma: no cover - should not be called
            raise AssertionError("DB execute must not be called for stopword-only query")

    repo = AdminRepository(DummyDb())  # type: ignore[arg-type]
    result = repo.search_document_chunks_text(
        tenant_id="00000000-0000-0000-0000-000000000001",
        normalized_query="что такое это",
        source_type="upload",
        limit=5,
    )
    assert result == []


def test_get_document_ingestion_job_by_id_scopes_by_tenant():
    captured: dict[str, object] = {}

    class DummyDb:
        def scalar(self, stmt):
            captured["stmt"] = stmt
            return None

    repo = AdminRepository(DummyDb())  # type: ignore[arg-type]
    repo.get_document_ingestion_job_by_id(
        tenant_id="00000000-0000-0000-0000-000000000001",
        job_id="00000000-0000-0000-0000-0000000000aa",
    )

    stmt = captured["stmt"]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    lower_sql = sql.lower()
    assert "where" in lower_sql
    assert "document_ingestion_jobs.id" in lower_sql
    assert "document_ingestion_jobs.tenant_id" in lower_sql


def test_claim_document_ingestion_job_scopes_by_tenant():
    captured: dict[str, object] = {}

    class DummyDb:
        def scalar(self, stmt):
            captured["stmt"] = stmt
            return None

        def rollback(self):
            return None

        def commit(self):
            return None

    repo = AdminRepository(DummyDb())  # type: ignore[arg-type]
    claimed = repo.claim_document_ingestion_job(
        tenant_id="00000000-0000-0000-0000-000000000001",
        job_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert claimed is None

    stmt = captured["stmt"]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    lower_sql = sql.lower()
    assert "update document_ingestion_jobs" in lower_sql
    assert "document_ingestion_jobs.id" in lower_sql
    assert "document_ingestion_jobs.tenant_id" in lower_sql
