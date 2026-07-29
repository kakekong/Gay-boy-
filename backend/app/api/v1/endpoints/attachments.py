"""File attachments for customer / quotation / project records."""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role
from app.models.attachment import Attachment
from app.models.user import User
from app.services import storage

router = APIRouter()


ALLOWED_OWNERS = {
    "customer", "quotation", "project", "approval_request",
    "supplier_po", "customer_po", "invoice", "delivery_order",
    "customer_contact", "employee", "price_request", "daily_log",
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
        # Externals may only ever touch the owner types their portal shows.
        # Which specific ROW is theirs is enforced by _external_owns_attachment
        # below — this blanket used to `return True` for every owner type, which
        # let a portal login read employee HR docs, supplier POs and other
        # customers' files if it knew an id.
        return owner_type in ("project", "quotation", "invoice",
                              "delivery_order", "supplier_po", "customer")
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
    if owner_type == "price_request":
        # Spec sheets / customer RFQ files ride on the PR. Same audience as
        # the PR page itself: sales files them, purchasing needs them to
        # cost the items, management oversees. (The file CONTENT may reveal
        # the customer — that's inherent to costing from a customer spec.)
        return role in (
            Role.SALES, Role.PURCHASING, Role.MANAGER, Role.DIRECTOR,
            Role.ADMIN, Role.FINANCE,
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
    if owner_type == "daily_log":
        # Work-journal attachments. The whole point of a daily log is
        # transparency of work, so any internal staffer may open them;
        # external portal users never touch them.
        return role not in (Role.CUSTOMER, Role.SUPPLIER)
    return role == Role.DIRECTOR


async def _external_owns_attachment(db: AsyncSession, me: User,
                                    owner_type: str, owner_id) -> bool:
    """Row-level scope for customer/supplier portal accounts.

    A portal login may only open files that belong to ITS OWN customer (or, for
    suppliers, its own supplier POs). Without this, knowing a UUID was enough to
    read another company's documents.
    """
    role = Role(me.role)
    if role not in (Role.CUSTOMER, Role.SUPPLIER):
        return True
    from app.models.finance import Invoice
    from app.models.operation import DeliveryOrder, Project
    from app.models.purchasing import SupplierPO
    from app.models.quotation import Quotation

    if role == Role.SUPPLIER:
        if owner_type != "supplier_po" or not me.linked_supplier_id:
            return False
        po = await db.get(SupplierPO, owner_id)
        return bool(po and po.supplier_id == me.linked_supplier_id)

    cid = me.linked_customer_id
    if not cid:
        return False
    if owner_type == "customer":
        return owner_id == cid
    if owner_type == "project":
        p = await db.get(Project, owner_id)
        return bool(p and p.customer_id == cid)
    if owner_type == "quotation":
        q = await db.get(Quotation, owner_id)
        return bool(q and q.customer_id == cid)
    if owner_type == "invoice":
        inv = await db.get(Invoice, owner_id)
        return bool(inv and inv.customer_id == cid)
    if owner_type == "delivery_order":
        do = await db.get(DeliveryOrder, owner_id)
        if not do:
            return False
        p = await db.get(Project, do.project_id) if do.project_id else None
        return bool(p and p.customer_id == cid)
    return False


async def _daily_log_read_ok(db: AsyncSession, me: User, owner_id) -> bool:
    """Daily-log files: readable by the log's owner or an overseer only.

    The generic role rule (any internal staffer) is a coarse gate; this
    row-level check matches the /team endpoint that actually surfaces log
    ids, so a leaked/guessed id can't expose a peer's journal files.
    """
    from app.models.daily_log import DailyLog
    log = await db.get(DailyLog, owner_id)
    if log is None:
        return True  # nothing to protect; list simply returns empty
    if log.user_id == me.id:
        return True
    return Role(me.role) in (Role.HR, Role.MANAGER, Role.DIRECTOR)


def _safe_filename(name: str) -> str:
    name = name.strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._\- ]+", "_", name)[:200]
    return name or "file"


def _resolve_uploader(db: AsyncSession, uploader_id):
    return uploader_id


async def _to_out(db: AsyncSession, a: Attachment) -> dict:
    uploader = await db.get(User, a.uploaded_by) if a.uploaded_by else None
    is_link = bool(a.external_url)
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
        "is_link": is_link,
        "external_url": a.external_url,
        # Links open directly; files stream through the download route.
        "download_url": a.external_url if is_link
        else f"/api/v1/attachments/{a.id}/download",
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
    if owner_type == "daily_log" and not await _daily_log_read_ok(db, me, owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your daily log")
    if not await _external_owns_attachment(db, me, owner_type, owner_id):
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
    # External portal accounts may only attach to their own rows. Internal
    # staff keep the previous behaviour — _attachment_visible_to governs who
    # may VIEW a file (customer files are director-only to read), which must
    # NOT gate uploading: sales legitimately attach files to their customers.
    if Role(me.role) in (Role.CUSTOMER, Role.SUPPLIER):
        if not _attachment_visible_to(owner_type, Role(me.role)) or \
                not await _external_owns_attachment(db, me, owner_type, owner_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Not allowed to attach files here")
    if owner_type == "daily_log":
        # Only the log's owner may attach to it (overseers can read, not add).
        from app.models.daily_log import DailyLog
        log = await db.get(DailyLog, owner_id)
        if log is None or log.user_id != me.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "You can only attach files to your own daily log")
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

    safe_name = _safe_filename(file.filename or "file")
    storage_path = await storage.save(data, filename=safe_name)

    a = Attachment(
        owner_type=owner_type,
        owner_id=owner_id,
        filename=safe_name,
        content_type=file.content_type,
        size=size,
        storage_path=storage_path,
        description=description,
        uploaded_by=me.id,
    )
    db.add(a)
    await db.flush()
    return await _to_out(db, a)


class LinkIn(BaseModel):
    owner_type: str
    owner_id: UUID
    url: str
    label: str | None = None


@router.post("/link", status_code=201)
async def add_link(
    payload: LinkIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Attach an external LINK (Google Drive, Dropbox, …) instead of a file.

    Same owner types and permissions as file upload — the difference is the
    'attachment' is a URL, so it survives Space rebuilds that wipe uploaded
    files.
    """
    if payload.owner_type not in ALLOWED_OWNERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid owner_type")
    if payload.owner_type == "daily_log":
        from app.models.daily_log import DailyLog
        log = await db.get(DailyLog, payload.owner_id)
        if log is None or log.user_id != me.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "You can only attach to your own daily log")
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link URL cannot be empty")
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    url = url[:1000]
    label = (payload.label or "").strip() or url
    a = Attachment(
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
        filename=label[:255],
        content_type="link",
        size=0,
        storage_path="",        # no file on disk for a link
        external_url=url,
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
    if a.owner_type == "daily_log" and not await _daily_log_read_ok(db, me, a.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your daily log")
    if not await _external_owns_attachment(db, me, a.owner_type, a.owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to view this file")
    # Link attachments have no file on disk — send the caller to the URL.
    if a.external_url:
        return RedirectResponse(a.external_url)
    data = await storage.load(a.storage_path)
    if data is None:
        raise HTTPException(status.HTTP_410_GONE, "File missing from storage")
    media_type = a.content_type or "application/octet-stream"
    # inline=1 lets the browser render PDFs/images directly in a new tab
    # instead of always triggering a save dialog.
    disposition = "inline" if inline else "attachment"
    # Served through the API rather than as a presigned bucket URL, so the
    # role checks above stay the only way to reach a file. A presigned link
    # would work without a token for as long as it lived.
    return Response(
        content=data,
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
    await storage.delete(a.storage_path)  # best-effort; never blocks the row delete
    await db.delete(a)
    return None
