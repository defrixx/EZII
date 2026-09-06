from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Document, StorageCleanupTask
from app.services.vector_service import VectorService


def safe_unlink(value: str | None) -> None:
    if not value:
        return
    root=Path(get_settings().document_storage_path).resolve();path=Path(value).resolve()
    if path!=root and root not in path.parents:
        raise ValueError("cleanup_path_outside_storage")
    path.unlink(missing_ok=True)
    parent=path.parent
    while parent!=root and parent.exists():
        try: parent.rmdir()
        except OSError: break
        parent=parent.parent


def process_cleanup_tasks(db:Session)->dict[str,int]:
    tasks=list(db.scalars(select(StorageCleanupTask).where(StorageCleanupTask.status=="pending").order_by(StorageCleanupTask.created_at)))
    completed=failed=0
    for task in tasks:
        task.attempts+=1;task.updated_at=datetime.now(timezone.utc)
        try:
            if task.vector_model_id and task.document_id: VectorService().delete_document(task.vector_model_id,task.knowledge_base_id,task.document_id)
            safe_unlink(task.storage_path);task.status="completed";task.error_code=None;completed+=1
        except Exception as exc:
            task.error_code=type(exc).__name__;failed+=1
    db.flush()
    completed_document_ids={task.document_id for task in tasks if task.status=="completed" and task.document_id}
    for document_id in completed_document_ids:
        remaining=db.scalar(select(StorageCleanupTask.id).where(StorageCleanupTask.document_id==document_id,StorageCleanupTask.status=="pending").limit(1))
        if not remaining:
            document=db.get(Document,document_id)
            if document: db.delete(document)
    db.commit();return {"completed":completed,"pending":failed}
