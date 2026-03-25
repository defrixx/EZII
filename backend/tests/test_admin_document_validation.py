import pytest
from pydantic import ValidationError

from app.schemas.admin import DocumentUpdateIn, DocumentUploadForm


def test_document_upload_form_rejects_oversized_metadata_json():
    oversized = {"notes": "x" * 9000}
    with pytest.raises(ValueError):
        DocumentUploadForm.from_form(
            title="Policy",
            enabled_in_retrieval=True,
            metadata_json=f'{{"notes":"{oversized["notes"]}"}}',
        )


def test_document_update_normalizes_and_limits_tags():
    payload = DocumentUpdateIn(
        metadata_json={"tags": [" Security ", "security", "ops"]},
    )
    assert payload.metadata_json == {"tags": ["Security", "ops"]}


def test_document_update_rejects_oversized_metadata_json():
    with pytest.raises(ValidationError):
        DocumentUpdateIn(metadata_json={"notes": "x" * 9000})
