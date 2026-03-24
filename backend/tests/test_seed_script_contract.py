from pathlib import Path


def test_seed_metadata_is_object_not_json_string():
    root = Path(__file__).resolve().parents[2]
    seed_text = (root / "scripts" / "seed.py").read_text(encoding="utf-8")

    assert '"metadata": Json({"domain": e["domain"]})' in seed_text
    assert "json.dumps({\"domain\": e[\"domain\"]}" not in seed_text


def test_seed_glossary_entries_are_idempotent_by_content():
    root = Path(__file__).resolve().parents[2]
    seed_text = (root / "scripts" / "seed.py").read_text(encoding="utf-8")

    assert "WHERE NOT EXISTS (" in seed_text
    assert "AND term = :term" in seed_text
    assert "AND definition = :definition" in seed_text


def test_seed_users_and_default_glossary_are_idempotent_by_business_keys():
    root = Path(__file__).resolve().parents[2]
    seed_text = (root / "scripts" / "seed.py").read_text(encoding="utf-8")

    assert "ON CONFLICT (tenant_id, email) DO UPDATE SET" in seed_text
    assert "ON CONFLICT (tenant_id, name) DO UPDATE SET" in seed_text
    assert "SELECT id" in seed_text
    assert 'AND name = :name' in seed_text
