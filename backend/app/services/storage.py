"""Where uploaded files actually live.

Two backends, chosen by `STORAGE_BACKEND`:

* **local** — a directory on disk (`STORAGE_LOCAL_DIR`). What we have always
  done. On a host with no persistent disk this loses every upload on redeploy,
  which is exactly why the S3 backend exists.
* **s3** — any S3-compatible object store. Written for Cloudflare R2, which
  needs `S3_ENDPOINT_URL` pointing at
  `https://<account-id>.r2.cloudflarestorage.com` and `S3_REGION=auto`. Plain
  AWS S3 works too: leave the endpoint unset.

**Reads dispatch on the stored path, not on the current setting.** A row whose
`storage_path` starts with `s3://` is fetched from the bucket; anything else is
read from disk. That is what makes the switch survivable — flip the setting and
every file uploaded before the flip still downloads, with no migration and no
downtime. `scripts/migrate_storage.py` moves the old ones across afterwards, at
your leisure.

The same dispatch-on-what-is-stored rule is what lets the *key layout* change
without a migration: see `build_key`, which now files objects under the
document's number rather than the month it was uploaded.

boto3 is synchronous, so every call goes through a worker thread. Blocking the
event loop on a network round-trip would stall every other request on the
process, and there is only one process.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from collections.abc import Sequence

from anyio import to_thread

from app.core.config import settings

logger = logging.getLogger(__name__)

S3_PREFIX = "s3://"


def using_s3() -> bool:
    return settings.STORAGE_BACKEND.lower() == "s3"


@lru_cache
def _client():
    """The boto3 S3 client, built once.

    Cached because constructing one parses botocore's bundled JSON service
    models — cheap once, wasteful per upload.
    """
    import boto3
    from botocore.config import Config

    opts = {
        "signature_version": "s3v4",
        "retries": {"max_attempts": 3, "mode": "standard"},
        # Newer boto3 releases attach CRC32 checksum headers to every upload by
        # default. R2 rejects requests carrying them, so ask for checksums only
        # where the protocol requires them. These two keys do not exist on
        # botocore before ~1.36 — hence the fallback rather than a hard pin,
        # so the module works across the versions a rebuild might resolve to.
        "request_checksum_calculation": "when_required",
        "response_checksum_validation": "when_required",
    }
    try:
        config = Config(**opts)
    except TypeError:
        for k in ("request_checksum_calculation", "response_checksum_validation"):
            opts.pop(k, None)
        config = Config(**opts)

    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL or None,
        region_name=settings.S3_REGION or "auto",
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        config=config,
    )


def _slug(value: str | None, *, fallback: str, limit: int = 60) -> str:
    """A path segment safe for an object key: no slashes, no surprises.

    Object stores have no real directories — the key is one string and `/` is
    only a display convention — so a stray slash inside a segment silently
    invents a folder level. Everything outside a small safe set collapses to
    `-`.
    """
    out = "".join(
        ch if (ch.isalnum() or ch in "._-") else "-"
        for ch in (value or "")
    ).strip("-._")[:limit]
    return out or fallback


def build_key(
    filename: str,
    label: str | None = None,
    *,
    owner_type: str | None = None,
    owner_id: object | None = None,
    owner_ref: str | Sequence[str] | None = None,
) -> str:
    """A collision-proof object key that says what the file is.

    The shape is::

        attachments/<owner_type>/<owner_ref>/<uuid8>_<label>_<name>

    Owner type first, because "show me every delivery order" is a question
    people actually ask; then the document, so everything belonging to one of
    them sits together::

        attachments/supplier_po/PO-2026-0043/1a2b3c4d_invoice_scan.pdf
        attachments/price_request/PR-2026-0117/9f8e7d6c_spec_sheet.pdf

    `owner_ref` is what the document is *called* — its number, or a name where
    it has no number — resolved by `services.doc_ref` from the owner row. When
    it cannot be resolved the UUID stands in, so a file always has somewhere to
    go; it is just filed somewhere less convenient.

    **The date used to be in here** — `.../<year>/<month>/<owner_id>/...` — and
    it was the wrong axis twice over. Nobody looks for the scans on a purchase
    order by the month somebody happened to upload them, and the documents'
    own numbers already carry the year (`PR-2026-0117`), so sorting by name
    sorts by time anyway. It survives in exactly one place: a file with no
    owner at all has nothing else to be filed under, so `misc/` keeps
    `<year>/<month>`.

    The uuid keeps its collision-proofing but is trimmed to 8 hex characters —
    at these volumes that is still far more than enough, and it leaves the
    human-readable filename visible in a bucket listing instead of pushed off
    the end of the column.

    **Existing rows are untouched.** Each row stores its own full
    `s3://bucket/key`, and reads dispatch on that string, so files written
    under the old layout keep downloading forever. Only new uploads use this;
    `scripts/migrate_storage.py --relayout` moves the old ones across.
    """
    safe = "".join(
        ch if (ch.isalnum() or ch in "._- ") else "_"
        for ch in (filename or "file")
    )[:200] or "file"

    scope = _slug(owner_type, fallback="misc", limit=40)
    stem = f"{uuid4().hex[:8]}_{_slug(label, fallback='')}_{safe}" if label \
        else f"{uuid4().hex[:8]}_{safe}"

    parts = ["attachments", scope]
    if owner_ref:
        # A reference may name more than one level — a contact is filed as
        # `(company, person)`. It says so by being a sequence; a plain string
        # is always exactly one folder. That distinction is the whole reason
        # this is not "split the string on `/`": a customer PO number is the
        # customer's own, and Indonesian ones look like `001/PO/IX/2026`.
        # Inferring folders from those slashes would scatter one document type
        # across a directory tree shaped like a date nobody asked for.
        segs = [owner_ref] if isinstance(owner_ref, str) else list(owner_ref)
        parts += [s for s in (_slug(x, fallback="", limit=80) for x in segs) if s]
    elif owner_id is not None:
        parts.append(_slug(str(owner_id), fallback="unknown", limit=64))
    else:
        # Nothing to file it under but the clock.
        now = datetime.now(UTC)
        parts += [f"{now.year}", f"{now.month:02d}"]
    parts.append(stem)
    return "/".join(parts)


def _split_s3(storage_path: str) -> tuple[str, str]:
    """`s3://bucket/some/key` -> `("bucket", "some/key")`."""
    rest = storage_path[len(S3_PREFIX):]
    bucket, _, key = rest.partition("/")
    return bucket, key


async def save(
    data: bytes,
    *,
    filename: str,
    label: str | None = None,
    owner_type: str | None = None,
    owner_id: object | None = None,
    db=None,
) -> str:
    """Store `data` and return the value to persist in `Attachment.storage_path`.

    Pass `owner_type`/`owner_id` when the caller knows what the file belongs
    to; they only shape the key (see `build_key`) and are optional so a caller
    without that context still works.

    Pass `db` as well and the key is filed under the document's *number*
    instead of its UUID. The lookup lives here rather than at each call site
    on purpose: there are a dozen places that upload a file, and a layout that
    depends on every one of them remembering to resolve a name is a layout
    that is half-applied within a year. Omitting `db` is not an error — the
    key falls back to the UUID.

    Local returns an absolute filesystem path, S3 an `s3://bucket/key` URI.
    Both use the same key, so the disk and the bucket browse identically.
    """
    owner_ref = None
    if db is not None and owner_type and owner_id is not None:
        from app.services.doc_ref import document_ref
        owner_ref = await document_ref(db, owner_type, owner_id)

    key = build_key(filename, label, owner_type=owner_type, owner_id=owner_id,
                    owner_ref=owner_ref)

    if not using_s3():
        path = Path(settings.STORAGE_LOCAL_DIR) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    bucket = settings.S3_BUCKET
    if not bucket:
        raise RuntimeError("STORAGE_BACKEND=s3 but S3_BUCKET is not set")
    await to_thread.run_sync(
        lambda: _client().put_object(Bucket=bucket, Key=key, Body=data)
    )
    return f"{S3_PREFIX}{bucket}/{key}"


async def load(storage_path: str) -> bytes | None:
    """The file's bytes, or None if it is not there any more."""
    if not storage_path:
        return None

    if storage_path.startswith(S3_PREFIX):
        bucket, key = _split_s3(storage_path)

        def _get():
            try:
                return _client().get_object(Bucket=bucket, Key=key)["Body"].read()
            except Exception:
                # Missing key, revoked credentials, bucket gone — all of them
                # mean the same thing to the caller: no file. The download
                # endpoint turns this into a 410 rather than a 500.
                logger.warning("storage: could not read %s", storage_path, exc_info=True)
                return None

        return await to_thread.run_sync(_get)

    return await to_thread.run_sync(
        lambda: Path(storage_path).read_bytes() if os.path.exists(storage_path) else None
    )


async def exists(storage_path: str) -> bool:
    if not storage_path:
        return False
    if storage_path.startswith(S3_PREFIX):
        bucket, key = _split_s3(storage_path)

        def _head():
            try:
                _client().head_object(Bucket=bucket, Key=key)
                return True
            except Exception:
                return False

        return await to_thread.run_sync(_head)
    return await to_thread.run_sync(lambda: os.path.exists(storage_path))


async def delete(storage_path: str) -> None:
    """Best-effort removal. A file we cannot delete must never block the
    database row from being deleted — an orphaned object is a tidiness problem,
    a stuck row is a user-facing one."""
    if not storage_path:
        return
    try:
        if storage_path.startswith(S3_PREFIX):
            bucket, key = _split_s3(storage_path)
            await to_thread.run_sync(
                lambda: _client().delete_object(Bucket=bucket, Key=key)
            )
        else:
            await to_thread.run_sync(
                lambda: os.remove(storage_path) if os.path.exists(storage_path) else None
            )
    except Exception:
        logger.warning("storage: could not delete %s", storage_path, exc_info=True)
