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


ALLOWED_OWNERS = {
    "customer", "quotation", "project", "approval_request",
    "supplier_po", "customer_po", "invoice", "delivery_order",
    "customer_contact", "employee",
}
MAX_FILE_SIZE_MB = 20


def _attachment_visible_to(owner_type: str, role: Role) -> bool:
    """Who may list/open files of a given owner type, inside the internal app.

    - External portal users (customer/supplier) keep access to their own
      scoped files — their drawing/upload links resolve through here.
    - Supplier-side files (supplier_po) stay limited to director + purchasing.
    - Approval attachments stay viewable by the approval reviewers (manager +
      director) so they can see what they're signing off.
    - Every other internal file (customer/quotation/project drawings & uploads)
      is director-only.
    """
    if role in (Role.CUSTOMER, Role.SUPPLIER):
        return True
    if owner_type == "supplier_po":
        return role in (Role.DIRECTOR, Role.PURCHASING)
    if owner_type == "approval_request":
        return role in (Role.MANAGER, Role.DIRECTOR)
    if owner_type == "project":
        # Project drawings are uploaded/reviewed by internal staff, so the same
        # internal set that can see the Drawings card may open the files.
        return role in (
            Role.DIRECTOR, Role.MANAGER, Role.ADMIN, Role.PURCHASING, Role.SALES,
        )
    if owner_type in ("invoice", "delivery_order"):
        # Invoice + DO + faktur pajak files: admin issues, finance approves;
        # management can see. Sales of the customer's deal can see too.
        return role in (
            Role.ADMIN, Role.FINANCE, Role.MANAGER, Role.DIRECTOR, Role.SALES,
        )
    if owner_type == "customer_contact":
        # KTP / ID card files per PIC. Same audience as the customer record
        # itself — sales works with these people daily.
        return role in (
            Role.SALES, Role.ADMIN, Role.MANAGER, Role.DIRECTOR, Role.FINANCE,
        )
    if owner_type == "employee":
        # Personnel docs — KTP, employment contract, NPWP (tax id), BPJS
        # (social-security id). HR files them; management/finance may view.
        return role in (
            Role.HR, Role.MANAGER, Role.DIRECTOR, Role.FINANCE,
        )
    return role == Role.DIRECTOR


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
    me: User = Depends(get_current_user),
):
    if owner_type not in ALLOWED_OWNERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid owner_type")
    if not _attachment_visible_to(owner_type, Role(me.role)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to view these files")
    rows = (await db.scalars(
        select(Attachment)
        .where(Attachment.owner_type == owner_type, Attachment.owner_id == owner_id)
        .order_by(Attachment.created_at.desc())
    )).all()
    return [await _to_out(db, a) for a in rows]


@router.get("/all")
async def list_all_attachments(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
    owner_type: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    """Director-only: every attachment in the system. Useful for auditing
    drawings/invoices/proofs uploaded by sales, suppliers, customers."""
    from app.core.permissions import Role
    if Role(me.role) != Role.DIRECTOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Director only")
    stmt = select(Attachment).order_by(Attachment.created_at.desc()).limit(limit)
    if owner_type:
        stmt = stmt.where(Attachment.owner_type == owner_type)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (Attachment.filename.ilike(like)) | (Attachment.description.ilike(like))
        )
    rows = (await db.scalars(stmt)).all()
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
    inline: bool = Query(False, description="Render in browser instead of forcing a download"),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    a = await db.get(Attachment, attachment_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not _attachment_visible_to(a.owner_type, Role(me.role)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to view this file")
    if not os.path.exists(a.storage_path):
        raise HTTPException(status.HTTP_410_GONE, "File missing from storage")
    media_type = a.content_type or "application/octet-stream"
    # inline=1 lets the browser render PDFs/images directly in a new tab
    # instead of always triggering a save dialog.
    disposition = "inline" if inline else "attachment"
    return FileResponse(
        a.storage_path,
        filename=a.filename,
        media_type=media_type,
        headers={
            "Content-Disposition":
                f'{disposition}; filename="{a.filename}"',
        },
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
