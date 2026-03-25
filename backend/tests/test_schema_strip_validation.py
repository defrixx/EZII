import pytest
from pydantic import ValidationError

from app.schemas.admin import DocumentUploadForm, WebsiteSnapshotCreate
from app.schemas.chat import ChatCreate, ChatUpdate, MessageCreate
from app.schemas.glossary import GlossaryCreate, GlossaryEntryCreate, GlossaryEntryUpdate, GlossaryUpdate


def test_chat_title_and_message_content_are_trimmed():
    chat = ChatCreate(title="  Incident response  ")
    updated = ChatUpdate(title="  SOC runbook ")
    message = MessageCreate(content="  How to rotate tokens?  ")

    assert chat.title == "Incident response"
    assert updated.title == "SOC runbook"
    assert message.content == "How to rotate tokens?"


def test_chat_and_message_reject_whitespace_only():
    with pytest.raises(ValidationError):
        ChatCreate(title="   ")
    with pytest.raises(ValidationError):
        ChatUpdate(title="   ")
    with pytest.raises(ValidationError):
        MessageCreate(content="   ")


def test_glossary_term_and_definition_are_trimmed():
    row = GlossaryEntryCreate(
        term="  phishing  ",
        definition="  social engineering attack  ",
    )
    patch = GlossaryEntryUpdate(term="  xdr  ", definition="  extended detection and response  ")

    assert row.term == "phishing"
    assert row.definition == "social engineering attack"
    assert patch.term == "xdr"
    assert patch.definition == "extended detection and response"


def test_glossary_name_and_description_are_trimmed():
    row = GlossaryCreate(name="  Cyber Glossary  ", description="  Glossary for SOC team  ")
    patch = GlossaryUpdate(name="  AppSec  ", description="  ")

    assert row.name == "Cyber Glossary"
    assert row.description == "Glossary for SOC team"
    assert patch.name == "AppSec"
    assert patch.description is None


def test_glossary_rejects_whitespace_only_name():
    with pytest.raises(ValidationError):
        GlossaryCreate(name="   ", description="ok")
    with pytest.raises(ValidationError):
        GlossaryUpdate(name="   ")


def test_glossary_rejects_whitespace_only_term_or_definition():
    with pytest.raises(ValidationError):
        GlossaryEntryCreate(term="   ", definition="valid")
    with pytest.raises(ValidationError):
        GlossaryEntryCreate(term="valid", definition="   ")
    with pytest.raises(ValidationError):
        GlossaryEntryUpdate(term="   ")
    with pytest.raises(ValidationError):
        GlossaryEntryUpdate(definition="   ")


def test_document_upload_form_title_is_trimmed_and_optional():
    row = DocumentUploadForm(title="  Incident Report  ", enabled_in_retrieval=True, metadata_json={})
    empty = DocumentUploadForm(title="   ", enabled_in_retrieval=True, metadata_json={})

    assert row.title == "Incident Report"
    assert empty.title is None


def test_website_snapshot_title_is_trimmed_and_optional():
    row = WebsiteSnapshotCreate(url="https://example.com", title="  Example  ", enabled_in_retrieval=True, tags=[])
    empty = WebsiteSnapshotCreate(url="https://example.com", title="   ", enabled_in_retrieval=True, tags=[])

    assert row.title == "Example"
    assert empty.title is None
