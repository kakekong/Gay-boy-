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


def build_key(filename: str, label: str | None = None) -> str:
    """A collision-proof object key, foldered by year/month like the disk
    layout so a migrated bucket browses the same way the old directory did."""
    now = datetime.now(UTC)
    safe = "".join(
        ch if (ch.isalnum() or ch in "._- ") else "_"
        for ch in (filename or "file")
    )[:200] or "file"
    stem = f"{uuid4().hex}_{label}_{safe}" if label else f"{uuid4().hex}_{safe}"
    return f"attachments/{now.year}/{now.month:02d}/{stem}"


def _split_s3(storage_path: str) -> tuple[str, str]:
    """`s3://bucket/some/key` -> `("bucket", "some/key")`."""
    rest = storage_path[len(S3_PREFIX):]
    bucket, _, key = rest.partition("/")
    return bucket, key


async def save(data: bytes, *, filename: str, label: str | None = None) -> str:
    """Store `data` and return the value to persist in `Attachment.storage_path`.

    Local returns an absolute filesystem path — byte-identical to what the old
    inline code produced, so nothing about existing rows changes. S3 returns an
    `s3://bucket/key` URI.
    """
    key = build_key(filename, label)

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
