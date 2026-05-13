"""File attachments for customer / quotation / project records."""

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role
from app.models.attachment import Attachment
from app.models.user import User

router = APIRouter()


ALLOWED_OWNERS = {"customer", "quotation", "project"}
MAX_FILE_SIZE_MB = 20


def _safe_filename(name: str) -> str:
    name = name.strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._\- ]+", "_", name)[:200]
    return name or "file"


def _storage_root() -> Path:
    root = Path(settings.STORAGE_LOCAL_DIR) / "attachments"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_uploader(db: AsyncSession, uploader_id):
    return uploader_id


async def _to_out(db: AsyncSession, a: Attachment) -> dict:
    uploader = await db.get(User, a.uploaded_by) if a.uploaded_by else None
    return {
        "id": str(a.id),
        "owner_type": a.owner_type,
        "owner_id": str(a.owner_id),
        "filename": a.filename,
        "content_type": a.content_type,
        "size": a.size,
        "description": a.description,
        "uploaded_by": str(a.uploaded_by) if a.uploaded_by else None,
        "uploaded_by_name": uploader.full_name if uploader else None,
        "uploaded_at": a.created_at,
        "download_url": f"/api/v1/attachments/{a.id}/download",
    }


@router.get("")
async def list_attachments(
    owner_type: str = Query(...),
    owner_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    _me: User = Depends(get_current_user),
):
    if owner_type not in ALLOWED_OWNERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid owner_type")
    rows = (await db.scalars(
        select(Attachment)
        .where(Attachment.owner_type == owner_type, Attachment.owner_id == owner_id)
        .order_by(Attachment.created_at.desc())
    )).all()
    return [await _to_out(db, a) for a in rows]


@router.post("", status_code=201)
async def upload_attachment(
    owner_type: str = Form(...),
    owner_id: UUID = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if owner_type not in ALLOWED_OWNERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid owner_type")
    # Read into memory to check size (small projects ok)
    data = await file.read()
    size = len(data)
    if size == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if size > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File too large (max {MAX_FILE_SIZE_MB} MB)",
        )

    now = datetime.now(UTC)
    folder = _storage_root() / str(now.year) / f"{now.month:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(file.filename or "file")
    storage_filename = f"{uuid4().hex}_{safe_name}"
    storage_path = folder / storage_filename
    storage_path.write_bytes(data)

    a = Attachment(
        owner_type=owner_type,
        owner_id=owner_id,
        filename=safe_name,
        content_type=file.content_type,
        size=size,
        storage_path=str(storage_path),
        description=description,
        uploaded_by=me.id,
    )
    db.add(a)
    await db.flush()
    return await _to_out(db, a)


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: UUID,
    db: AsyncSession = Depends(get_db),
    _me: User = Depends(get_current_user),
):
    a = await db.get(Attachment, attachment_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not os.path.exists(a.storage_path):
        raise HTTPException(status.HTTP_410_GONE, "File missing from storage")
    return FileResponse(
        a.storage_path,
        filename=a.filename,
        media_type=a.content_type or "application/octet-stream",
    )


@router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    a = await db.get(Attachment, attachment_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # Only uploader, admin, or director can delete
    if (
        a.uploaded_by != me.id
        and Role(me.role) not in (Role.ADMIN, Role.DIRECTOR)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only uploader or admin/director can delete")
    try:
        if os.path.exists(a.storage_path):
            os.remove(a.storage_path)
    except OSError:
        pass  # don't block the DB delete on a missing file
    await db.delete(a)
    return None
