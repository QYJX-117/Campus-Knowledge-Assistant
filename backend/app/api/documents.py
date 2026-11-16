"""Knowledge-base document CRUD, preview, download and batch routes."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ..database import get_db
from ..models.common import Result
from ..models.document import DocumentBatchBody, DocumentReviewBody, DocumentSearchBody
from ..rag.engine import rag_engine
from ..services.document_service import DocumentService
from .chat import admin_user, current_user


router = APIRouter(prefix="/api/documents", tags=["documents"])
course_router = APIRouter(prefix="/api/doc", tags=["documents"])


async def _upload(
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection,
    actor: sqlite3.Row | dict,
    file: UploadFile,
    title: str | None,
    category: str,
) -> dict:
    is_admin = actor["role"] == "ADMIN"
    if isinstance(actor, dict) and actor.get("guest"):
        uploader_id = DocumentService.guest_uploader_id(db)
        uploader_key = f"guest:{actor['guest_id']}"
    else:
        uploader_id = int(actor["id"])
        uploader_key = f"user:{uploader_id}"
    document = await DocumentService.upload(
        db, file, title, uploader_id, category,
        uploader_key=uploader_key, auto_approve=is_admin,
    )
    if is_admin:
        background_tasks.add_task(DocumentService.process_document, document["id"])
    return document


def _owner_key(actor: sqlite3.Row | dict) -> str | None:
    if actor["role"] == "ADMIN":
        return None
    if isinstance(actor, dict) and actor.get("guest"):
        return f"guest:{actor['guest_id']}"
    return f"user:{int(actor['id'])}"


@router.get("")
def list_documents_legacy(db: sqlite3.Connection = Depends(get_db), actor=Depends(current_user)):
    """Compatibility endpoint used by the existing dashboard."""
    return Result.ok(DocumentService.list_documents(db, page=1, page_size=100, uploader_key=_owner_key(actor))["items"])


@course_router.get("/list")
def list_documents(
    q: str = Query("", max_length=100),
    status: str | None = Query(None),
    review_status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: sqlite3.Connection = Depends(get_db),
    actor=Depends(current_user),
):
    return Result.ok(DocumentService.list_documents(
        db, query=q, status=status, review_status=review_status,
        page=page, page_size=page_size, uploader_key=_owner_key(actor),
    ))


@course_router.post("/search")
def search_document_chunks(body: DocumentSearchBody, _=Depends(admin_user)):
    return Result.ok(rag_engine.search_chunks(body.question, body.topK))


@router.post("", status_code=201)
async def upload_document_legacy(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=120)] = None,
    category: Annotated[str, Form(max_length=50)] = "其他",
    db: sqlite3.Connection = Depends(get_db),
    actor=Depends(current_user),
):
    return Result.ok(await _upload(background_tasks, db, actor, file, title, category))


@course_router.post("/upload", status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=120)] = None,
    category: Annotated[str, Form(max_length=50)] = "其他",
    db: sqlite3.Connection = Depends(get_db),
    actor=Depends(current_user),
):
    return Result.ok(await _upload(background_tasks, db, actor, file, title, category))


@course_router.get("/{document_id:int}")
def document_detail(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
    actor=Depends(current_user),
):
    document = DocumentService.get_document(db, document_id, uploader_key=_owner_key(actor))
    if document.get("preview_pending"):
        background_tasks.add_task(DocumentService.build_preview_cache, document_id)
    return Result.ok(document)


@course_router.get("/{document_id:int}/download")
def download_document(document_id: int, db: sqlite3.Connection = Depends(get_db), actor=Depends(current_user)):
    path, filename, media_type = DocumentService.file_for_download(db, document_id, _owner_key(actor))
    return FileResponse(path, media_type=media_type, filename=filename)


@course_router.put("/{document_id:int}")
async def update_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    title: Annotated[str | None, Form(max_length=120)] = None,
    category: Annotated[str | None, Form(max_length=50)] = None,
    file: Annotated[UploadFile | None, File()] = None,
    text_content: Annotated[str | None, Form(max_length=200_000)] = None,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(admin_user),
):
    document = await DocumentService.update_document(
        db, document_id, title, category, file, text_content,
    )
    if document["review_status"] == "APPROVED":
        background_tasks.add_task(DocumentService.process_document, document_id)
    return Result.ok(document)


def _reprocess(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection,
) -> dict:
    document = DocumentService.reprocess(db, document_id)
    background_tasks.add_task(DocumentService.process_document, document_id)
    return document


@router.post("/{document_id:int}/reprocess")
def reprocess_legacy(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(admin_user),
):
    return Result.ok(_reprocess(document_id, background_tasks, db))


@course_router.post("/{document_id:int}/reprocess")
def reprocess(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(admin_user),
):
    return Result.ok(_reprocess(document_id, background_tasks, db))


def _delete(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection,
    uploader_key: str | None = None,
) -> None:
    deleted = DocumentService.delete_document(db, document_id, uploader_key)
    if not deleted:
        raise HTTPException(404, "文档不存在")
    background_tasks.add_task(DocumentService.purge_deleted_index, deleted)


@router.delete("/{document_id:int}", status_code=204)
def delete_document_legacy(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
    actor=Depends(current_user),
):
    _delete(document_id, background_tasks, db, _owner_key(actor))


@course_router.delete("/{document_id:int}", status_code=204)
def delete_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
    actor=Depends(current_user),
):
    _delete(document_id, background_tasks, db, _owner_key(actor))


@course_router.post("/{document_id:int}/review")
def review_document(
    document_id: int,
    body: DocumentReviewBody,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
    admin: sqlite3.Row = Depends(admin_user),
):
    document = DocumentService.review_document(db, document_id, body.action, int(admin["id"]), body.note)
    if body.action == "approve":
        background_tasks.add_task(DocumentService.process_document, document_id)
    return Result.ok(document)


@course_router.post("/batch/action")
def batch_action(
    body: DocumentBatchBody,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(admin_user),
):
    ids = list(dict.fromkeys(body.ids))
    succeeded: list[int] = []
    failed: list[dict] = []
    for document_id in ids:
        try:
            if body.action == "delete":
                _delete(document_id, background_tasks, db)
            else:
                DocumentService.reprocess(db, document_id)
                background_tasks.add_task(DocumentService.process_document, document_id)
            succeeded.append(document_id)
        except HTTPException as exc:
            failed.append({"id": document_id, "reason": str(exc.detail)})
    return Result.ok({"succeeded": succeeded, "failed": failed})
