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
