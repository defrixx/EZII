from pathlib import Path


def test_seed_metadata_is_object_not_json_string():
    root = Path(__file__).resolve().parents[2]
    seed_text = (root / "scripts" / "seed.py").read_text(encoding="utf-8")

    assert '"metadata": {"domain": e["domain"]}' in seed_text
    assert "json.dumps({\"domain\": e[\"domain\"]}" not in seed_text
