"""Document upload, processing, metadata and lifecycle orchestration."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from ..config import settings
from ..database import connect, utc_now
from ..rag.engine import rag_engine


ALLOWED_SUFFIXES = {".pdf", ".doc", ".docx", ".txt", ".md"}
ALLOWED_STATUSES = {"PROCESSING", "READY", "ERROR"}
ALLOWED_REVIEW_STATUSES = {"PENDING", "APPROVED", "REJECTED"}
MAX_EDITABLE_CONTENT_CHARS = 200_000
_LOCKS: dict[int, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _document_lock(document_id: int) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(document_id, threading.RLock())


def _clean_filename(value: str) -> str:
    filename = Path((value or "").replace("\\", "/")).name.strip()
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename)
    if not filename or filename in {".", ".."}:
        raise HTTPException(400, "文件名不能为空")
    if len(filename) > 180:
        raise HTTPException(400, "文件名不能超过 180 个字符")
    return filename


def _validate_signature(suffix: str, head: bytes) -> None:
    if not head:
        raise HTTPException(400, "不能上传空文件")
    if suffix == ".pdf" and not head.startswith(b"%PDF-"):
        raise HTTPException(400, "文件内容不是有效的 PDF")
    if suffix == ".docx" and not head.startswith(b"PK"):
        raise HTTPException(400, "文件内容不是有效的 DOCX")
    if suffix == ".doc" and not (
        head.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
        or head.startswith(b"{\\rtf")
        or head.startswith(b"PK")
    ):
        raise HTTPException(400, "文件内容不是有效的 DOC")
    if suffix in {".txt", ".md"} and b"\x00" in head:
        raise HTTPException(400, "文本文件包含二进制内容")


def _safe_error(exc: Exception) -> str:
    message = str(exc).replace(str(settings.upload_dir), "<upload-dir>")
    return (message or exc.__class__.__name__)[:500]


class DocumentService:
    @staticmethod
    def _source_path(doc: sqlite3.Row | dict) -> Path | None:
        """Resolve uploaded and checked-in KB files without trusting arbitrary DB paths."""
        stored_name = str(doc["stored_name"] or "")
        candidates = [settings.upload_dir / stored_name]
        original_path = str(doc["original_path"] or "")
        if original_path:
            original = Path(original_path)
            candidates.append(original if original.is_absolute() else settings.knowledge_base_dir / original.name)
        if stored_name.startswith("kb:"):
            candidates.append(settings.knowledge_base_dir / stored_name.removeprefix("kb:"))

        allowed_roots = [settings.upload_dir.resolve(), settings.knowledge_base_dir.resolve()]
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                if resolved.is_file() and any(resolved.is_relative_to(root) for root in allowed_roots):
                    return resolved
            except (OSError, ValueError):
                continue
        return None

    @staticmethod
    def _extract_source_text(path: Path) -> str:
        if path.suffix.lower() in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        from ..rag.utils import extract_text

        return extract_text(path.read_bytes(), path.name).strip()

    @staticmethod
    def _preview_cache_key(doc: sqlite3.Row | dict, path: Path) -> str:
        content_hash = str(doc.get("content_hash") or "") if isinstance(doc, dict) else str(doc["content_hash"] or "")
        if content_hash:
            return content_hash
        try:
            stat = path.stat()
            return f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}"
        except OSError:
            return f"{path.name}:{doc['size']}"

    @staticmethod
    def _save_preview_cache(
        db: sqlite3.Connection,
        doc_id: int,
        text: str,
        cache_key: str,
        error: str | None = None,
    ) -> None:
        truncated = len(text) > MAX_EDITABLE_CONTENT_CHARS
        db.execute(
            """
            UPDATE documents SET preview_cache=?,preview_cache_key=?,preview_cache_truncated=?,
                preview_cached_at=?,preview_cache_error=? WHERE id=?
            """,
            (
                text[:MAX_EDITABLE_CONTENT_CHARS], cache_key, int(truncated),
                utc_now(), error, doc_id,
            ),
        )
        db.commit()

    @staticmethod
    def build_preview_cache(doc_id: int) -> None:
        """Extract a source document outside the request path and cache its Markdown."""
        with _document_lock(doc_id), connect() as db:
            doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not doc or str(doc["content_override"] or "").strip():
                return
            path = DocumentService._source_path(doc)
            if path is None:
                return
            cache_key = DocumentService._preview_cache_key(doc, path)
            if doc["preview_cache"] and doc["preview_cache_key"] == cache_key:
                return
            try:
                text = DocumentService._extract_source_text(path)
                DocumentService._save_preview_cache(db, doc_id, text, cache_key)
            except Exception as exc:
                db.execute(
                    "UPDATE documents SET preview_cache_error=?,preview_cached_at=? WHERE id=?",
                    (_safe_error(exc), utc_now(), doc_id),
                )
                db.commit()

    @staticmethod
    def guest_uploader_id(db: sqlite3.Connection) -> int:
        """Return the shared FK identity used for anonymous submissions."""
        email = "guest-uploader@system.local"
        row = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if row:
            return int(row["id"])
        from ..security import hash_password

        cur = db.execute(
            "INSERT INTO users(name,email,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?,?)",
            ("访客投稿", email, hash_password(uuid.uuid4().hex), "STUDENT", 0, utc_now()),
        )
        db.commit()
        return int(cur.lastrowid)

    @staticmethod
    async def _store_upload(file: UploadFile) -> dict[str, Any]:
        filename = _clean_filename(file.filename or "")
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(400, "仅支持 PDF、DOC、DOCX、TXT 和 Markdown 文件")

        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        final_path = settings.upload_dir / stored_name
        temporary_path = settings.upload_dir / f".{stored_name}.part"
        digest = hashlib.sha256()
        size = 0
        head = b""
        try:
            with temporary_path.open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(
                            413,
                            f"文件不能超过 {settings.max_upload_bytes // 1024 // 1024}MB",
                        )
                    if len(head) < 16:
                        head += chunk[: 16 - len(head)]
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            _validate_signature(suffix, head)
            temporary_path.replace(final_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

        return {
            "filename": filename,
            "stored_name": stored_name,
            "path": final_path,
            "suffix": suffix,
            "size": size,
            "content_hash": digest.hexdigest(),
            "mime_type": file.content_type or "application/octet-stream",
        }

    @staticmethod
    async def upload(
        db: sqlite3.Connection,
        file: UploadFile,
        title: str | None,
        user_id: int,
        category: str = "其他",
        uploader_key: str | None = None,
        auto_approve: bool = False,
    ) -> dict:
        stored = await DocumentService._store_upload(file)
        clean_title = (title or Path(stored["filename"]).stem).strip()[:120]
        if len(clean_title) < 2:
            stored["path"].unlink(missing_ok=True)
            raise HTTPException(400, "文档标题至少需要 2 个字符")
        now = utc_now()
        review_status = "APPROVED" if auto_approve else "PENDING"
        processing_step = "UPLOADED" if auto_approve else "AWAITING_REVIEW"
        try:
            cur = db.execute(
                """
                INSERT INTO documents(
                    title,filename,stored_name,mime_type,size,status,chunk_count,
                    source_url,category,error,uploaded_by,created_at,updated_at,
                    processing_step,content_hash,review_status,review_note,reviewed_by,
                    reviewed_at,uploader_key
                ) VALUES(?,?,?,?,?,'PROCESSING',0,'',?,NULL,?,?,?,?,?,?,NULL,?,?,?)
                """,
                (
                    clean_title, stored["filename"], stored["stored_name"],
                    stored["mime_type"], stored["size"], category.strip()[:50] or "其他",
                    user_id, now, now, processing_step, stored["content_hash"], review_status,
                    user_id if auto_approve else None, now if auto_approve else None,
                    uploader_key or f"user:{user_id}",
                ),
            )
            db.commit()
        except Exception:
            stored["path"].unlink(missing_ok=True)
            raise
        return DocumentService.get_document(db, int(cur.lastrowid), include_chunks=False)

    @staticmethod
    def _set_step(db: sqlite3.Connection, doc_id: int, step: str) -> None:
        db.execute(
            "UPDATE documents SET status='PROCESSING',processing_step=?,updated_at=? WHERE id=?",
            (step, utc_now(), doc_id),
        )
        db.commit()

    @staticmethod
    def process_document(doc_id: int) -> None:
        """Idempotent background task: replace old vectors and chunk metadata."""
        with _document_lock(doc_id), connect() as db:
            doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not doc:
                return
            if doc["review_status"] != "APPROVED":
                return
            path = DocumentService._source_path(doc)
            text_override = doc["content_override"]
            if path is None and not text_override:
                db.execute(
                    "UPDATE documents SET status='ERROR',processing_step='FAILED',error=?,updated_at=? WHERE id=?",
                    ("原始文件不存在", utc_now(), doc_id),
                )
                db.commit()
                return
            try:
                DocumentService._set_step(db, doc_id, "EXTRACTING")

                # Extract once during indexing and reuse the structured Markdown
                # for detail/edit requests.  This prevents PDF OCR and DOCX
                # parsing from running again on every modal open.
                indexed_text = text_override
                if indexed_text is None and path is not None:
                    indexed_text = DocumentService._extract_source_text(path)
                    DocumentService._save_preview_cache(
                        db, doc_id, indexed_text,
                        DocumentService._preview_cache_key(doc, path),
                    )

                def progress(step: str) -> None:
                    DocumentService._set_step(db, doc_id, step)

                count = rag_engine.add_document(
                    path or (settings.upload_dir / doc["filename"]),
                    doc_id,
                    title=doc["title"],
                    category=doc["category"] or "其他",
                    source_url=doc["source_url"] or "",
                    text_override=indexed_text,
                    progress_callback=progress,
                )
                if count <= 0:
                    raise ValueError("文档切分后没有生成有效文本块")

                chunks = rag_engine.get_document_chunks(doc_id, doc["stored_name"])
                db.execute("DELETE FROM document_chunks WHERE document_id=?", (doc_id,))
                db.executemany(
                    """
                    INSERT INTO document_chunks(document_id,chunk_index,content,page_number,created_at)
                    VALUES(?,?,?,?,?)
                    """,
                    [
                        (doc_id, item["chunk_index"], item["content"], item["page_number"], utc_now())
                        for item in chunks
                    ],
                )
                db.execute(
                    """
                    UPDATE documents
                    SET status='READY',processing_step='COMPLETED',chunk_count=?,error=NULL,updated_at=?
                    WHERE id=?
                    """,
                    (count, utc_now(), doc_id),
                )
                db.commit()
            except Exception as exc:
                db.rollback()
                db.execute(
                    """
                    UPDATE documents
                    SET status='ERROR',processing_step='FAILED',error=?,updated_at=?
                    WHERE id=?
                    """,
                    (_safe_error(exc), utc_now(), doc_id),
                )
                db.commit()

    @staticmethod
    def list_documents(
        db: sqlite3.Connection,
        query: str = "",
        status: str | None = None,
        review_status: str | None = None,
        page: int = 1,
        page_size: int = 10,
        uploader_key: str | None = None,
    ) -> dict:
        if status and status not in ALLOWED_STATUSES:
            raise HTTPException(400, "无效的处理状态")
        if review_status and review_status not in ALLOWED_REVIEW_STATUSES:
            raise HTTPException(400, "无效的审核状态")
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        clauses: list[str] = []
        values: list[Any] = []
        if query.strip():
            escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(d.title LIKE ? ESCAPE '\\' OR d.filename LIKE ? ESCAPE '\\')")
            values.extend([f"%{escaped}%", f"%{escaped}%"])
        if status:
            clauses.append("d.status=?")
            values.append(status)
        if review_status:
            clauses.append("d.review_status=?")
            values.append(review_status)
        if uploader_key:
            clauses.append("d.uploader_key=?")
            values.append(uploader_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = db.execute(f"SELECT COUNT(*) FROM documents d {where}", values).fetchone()[0]
        rows = db.execute(
            f"""
            SELECT d.*,u.name AS uploader_name
            FROM documents d JOIN users u ON u.id=d.uploaded_by
            {where}
            ORDER BY d.created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*values, page_size, (page - 1) * page_size],
        ).fetchall()
        return {
            "items": [dict(row) | {"size": int(row["size"])} for row in rows],
            "total": int(total),
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def get_document(
        db: sqlite3.Connection,
        doc_id: int,
        include_chunks: bool = True,
        uploader_key: str | None = None,
    ) -> dict:
        row = db.execute(
            """
            SELECT d.*,u.name AS uploader_name
            FROM documents d JOIN users u ON u.id=d.uploaded_by WHERE d.id=?
            """,
            (doc_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "文档不存在")
        if uploader_key and row["uploader_key"] != uploader_key:
            raise HTTPException(404, "文档不存在")
        result = dict(row)
        if include_chunks:
            chunks = db.execute(
                "SELECT chunk_index,content,page_number FROM document_chunks WHERE document_id=? ORDER BY chunk_index",
                (doc_id,),
            ).fetchall()
            recovered = [dict(chunk) for chunk in chunks]
            if not recovered:
                recovered = rag_engine.get_document_chunks(doc_id, row["stored_name"])
                if recovered:
                    db.executemany(
                        """
                        INSERT OR REPLACE INTO document_chunks(
                            document_id,chunk_index,content,page_number,created_at
                        ) VALUES(?,?,?,?,?)
                        """,
                        [
                            (doc_id, item["chunk_index"], item["content"], item["page_number"], utc_now())
                            for item in recovered
                        ],
                    )
                    db.commit()
            preview = str(row["content_override"] or "").strip()
            preview_source = "edited" if preview else ""
            preview_pending = False
            if not preview:
                source_path = DocumentService._source_path(row)
                cache_key = DocumentService._preview_cache_key(row, source_path) if source_path else ""
                cached = str(row["preview_cache"] or "").strip()
                if cached and row["preview_cache_key"] == cache_key:
                    preview = cached
                    preview_source = "source-cache"
                elif source_path and source_path.suffix.lower() in {".txt", ".md"}:
                    # Plain text is cheap and safe to parse inline.  Office and
                    # scanned PDF extraction is deferred to a background task.
                    try:
                        preview = DocumentService._extract_source_text(source_path)
                        DocumentService._save_preview_cache(db, doc_id, preview, cache_key)
                        preview_source = "source"
                    except Exception:
                        preview = ""
                elif source_path:
                    preview_pending = True
            # Retrieval chunks remain an immediate, fast fallback while a
            # DOCX/DOC/PDF source is being converted into the preview cache.
            if not preview:
                preview = "\n\n".join(chunk["content"] for chunk in recovered)
                preview_source = "chunks" if preview else ""
            result["chunks"] = recovered
            result["preview_format"] = "markdown"
            result["preview"] = preview[: settings.max_preview_chars]
            result["preview_source"] = preview_source
            result["preview_pending"] = preview_pending
            result["preview_cache_error"] = row["preview_cache_error"]
            result["preview_truncated"] = bool(row["preview_cache_truncated"]) or len(preview) > settings.max_preview_chars
            result["editable_content"] = preview[:MAX_EDITABLE_CONTENT_CHARS]
            result["editable_truncated"] = bool(row["preview_cache_truncated"]) or len(preview) > MAX_EDITABLE_CONTENT_CHARS
        return result

    @staticmethod
    def file_for_download(
        db: sqlite3.Connection,
        doc_id: int,
        uploader_key: str | None = None,
    ) -> tuple[Path, str, str]:
        doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(404, "文档不存在")
        if uploader_key and doc["uploader_key"] != uploader_key:
            raise HTTPException(404, "文档不存在")
        path = DocumentService._source_path(doc)
        if path is None:
            raise HTTPException(404, "原始文件不存在")
        return path, doc["filename"], doc["mime_type"]

    @staticmethod
    async def update_document(
        db: sqlite3.Connection,
        doc_id: int,
        title: str | None = None,
        category: str | None = None,
        file: UploadFile | None = None,
        text_content: str | None = None,
    ) -> dict:
        if file is not None and text_content is not None:
            raise HTTPException(400, "替换原始文件与编辑知识正文不能同时提交")
        replacement = await DocumentService._store_upload(file) if file else None
        with _document_lock(doc_id):
            doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not doc:
                if replacement:
                    replacement["path"].unlink(missing_ok=True)
                raise HTTPException(404, "文档不存在")
            clean_title = (title if title is not None else doc["title"]).strip()[:120]
            if len(clean_title) < 2:
                if replacement:
                    replacement["path"].unlink(missing_ok=True)
                raise HTTPException(400, "文档标题至少需要 2 个字符")
            old_path = DocumentService._source_path(doc)
            override = doc["content_override"]
            edited_at = doc["content_edited_at"]
            if replacement:
                override = None
                edited_at = None
            elif text_content is not None:
                override = text_content.strip()
                if len(override) < 2:
                    raise HTTPException(400, "知识正文至少需要 2 个字符")
                if len(override) > MAX_EDITABLE_CONTENT_CHARS:
                    raise HTTPException(413, f"知识正文不能超过 {MAX_EDITABLE_CONTENT_CHARS:,} 个字符")
                edited_at = utc_now()
            try:
                db.execute(
                    """
                    UPDATE documents SET title=?,category=?,filename=?,stored_name=?,mime_type=?,size=?,
                        content_hash=?,original_path=?,content_override=?,content_edited_at=?,
                        preview_cache=?,preview_cache_key=?,preview_cache_truncated=?,preview_cached_at=?,preview_cache_error=?,
                        status='PROCESSING',processing_step='UPLOADED',chunk_count=0,
                        error=NULL,updated_at=? WHERE id=?
                    """,
                    (
                        clean_title,
                        (category if category is not None else doc["category"]) or "其他",
                        replacement["filename"] if replacement else doc["filename"],
                        replacement["stored_name"] if replacement else doc["stored_name"],
                        replacement["mime_type"] if replacement else doc["mime_type"],
                        replacement["size"] if replacement else doc["size"],
                        replacement["content_hash"] if replacement else doc["content_hash"],
                        None if replacement else doc["original_path"],
                        override, edited_at,
                        None if (replacement or text_content is not None) else doc["preview_cache"],
                        None if (replacement or text_content is not None) else doc["preview_cache_key"],
                        0 if (replacement or text_content is not None) else doc["preview_cache_truncated"],
                        None if (replacement or text_content is not None) else doc["preview_cached_at"],
                        None if (replacement or text_content is not None) else doc["preview_cache_error"],
                        utc_now(), doc_id,
                    ),
                )
                db.commit()
            except Exception:
                if replacement:
                    replacement["path"].unlink(missing_ok=True)
                raise
            if replacement and old_path and old_path != replacement["path"]:
                try:
                    if old_path.is_relative_to(settings.upload_dir.resolve()) and not doc["stored_name"].startswith("seed-"):
                        old_path.unlink(missing_ok=True)
                except ValueError:
                    pass
        return DocumentService.get_document(db, doc_id, include_chunks=False)

    @staticmethod
    def reprocess(db: sqlite3.Connection, doc_id: int) -> dict:
        doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(404, "文档不存在")
        if doc["review_status"] != "APPROVED":
            raise HTTPException(409, "文档审核通过后才能重新处理")
        if DocumentService._source_path(doc) is None and not doc["content_override"]:
            raise HTTPException(404, "原始文件不存在")
        db.execute(
            """
            UPDATE documents SET status='PROCESSING',processing_step='UPLOADED',
                chunk_count=0,error=NULL,updated_at=? WHERE id=?
            """,
            (utc_now(), doc_id),
        )
        db.commit()
        return DocumentService.get_document(db, doc_id, include_chunks=False)

    @staticmethod
    def review_document(
        db: sqlite3.Connection,
        doc_id: int,
        action: str,
        reviewer_id: int,
        note: str = "",
    ) -> dict:
        doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(404, "文档不存在")
        if doc["review_status"] != "PENDING":
            raise HTTPException(409, "该文档已完成审核，请刷新列表")
        if action not in {"approve", "reject"}:
            raise HTTPException(400, "无效的审核操作")
        clean_note = note.strip()[:500]
        if action == "reject" and len(clean_note) < 2:
            raise HTTPException(400, "驳回时请填写至少 2 个字符的原因")
        now = utc_now()
        if action == "approve":
            db.execute(
                """
                UPDATE documents SET review_status='APPROVED',review_note=?,reviewed_by=?,reviewed_at=?,
                    status='PROCESSING',processing_step='UPLOADED',chunk_count=0,error=NULL,updated_at=?
                WHERE id=?
                """,
                (clean_note or "审核通过", reviewer_id, now, now, doc_id),
            )
        else:
            db.execute(
                """
                UPDATE documents SET review_status='REJECTED',review_note=?,reviewed_by=?,reviewed_at=?,
                    status='ERROR',processing_step='REJECTED',error=NULL,updated_at=?
                WHERE id=?
                """,
                (clean_note, reviewer_id, now, now, doc_id),
            )
        db.commit()
        return DocumentService.get_document(db, doc_id, include_chunks=False)

    @staticmethod
    def delete_document(db: sqlite3.Connection, doc_id: int, uploader_key: str | None = None) -> dict | None:
        """Delete relational/file data immediately; FAISS cleanup is deferred."""
        with _document_lock(doc_id):
            doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not doc:
                return None
            if uploader_key and doc["uploader_key"] != uploader_key:
                return None
            if uploader_key and doc["review_status"] == "APPROVED":
                raise HTTPException(403, "已通过的知识库文档请联系管理员删除")
            path = settings.upload_dir / doc["stored_name"]
            quarantine = settings.upload_dir / f".{doc['stored_name']}.deleting"
            moved = False
            try:
                # Retrieval filters the tombstone immediately, so the user
                # never sees a deleted document while the expensive FAISS
                # compaction runs after the HTTP response.
                rag_engine.tombstone_document(doc_id, doc["stored_name"])
                if path.exists() and not doc["stored_name"].startswith("seed-"):
                    path.replace(quarantine)
                    moved = True
                db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
                db.commit()
                if moved:
                    quarantine.unlink(missing_ok=True)
                return {"id": doc_id, "stored_name": doc["stored_name"]}
            except Exception:
                db.rollback()
                rag_engine.clear_document_tombstone(doc_id, doc["stored_name"])
                if moved and quarantine.exists():
                    quarantine.replace(path)
                raise

    @staticmethod
    def purge_deleted_index(document: dict) -> None:
        """Compact FAISS after deletion without holding up the delete request."""
        try:
            rag_engine.delete_document(
                int(document["id"]), stored_name=document.get("stored_name"),
            )
        except Exception as exc:
            # Keep the tombstone in place so stale vectors remain invisible;
            # the next explicit rebuild can reclaim them safely.
            print(f"[WARN] Deferred document index cleanup failed: {_safe_error(exc)}")

    @staticmethod
    def mark_interrupted_as_failed(db: sqlite3.Connection) -> int:
        cur = db.execute(
            """
            UPDATE documents SET status='ERROR',processing_step='FAILED',
                error='服务重启导致处理任务中断，请点击重新处理',updated_at=?
            WHERE status='PROCESSING' AND review_status='APPROVED'
            """,
            (utc_now(),),
        )
        db.commit()
        return cur.rowcount
