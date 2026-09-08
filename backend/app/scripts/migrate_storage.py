"""Move stored files to where they ought to be — across backends, or across layouts.

Two jobs, because they are the same job: read the bytes, write them at the key
`storage.build_key` produces today, point the row at the new place.

**Copy local files into the bucket** (the default). Not needed to *switch*
backends — reads follow whatever path each row stores, so flipping
`STORAGE_BACKEND=s3` works immediately and old files keep serving off the disk.
This is for afterwards, when you want to detach the disk.

    python -m app.scripts.migrate_storage              # dry run
    python -m app.scripts.migrate_storage --apply

**Re-file what is already in the bucket** (`--relayout`). Objects written
before the layout changed sit under `attachments/<type>/<year>/<month>/<uuid>/`
— filed by the month somebody uploaded them, under an id nobody can read.
Everything written since sits under the document's number. Both download fine;
only a person browsing the bucket can tell, and to them the bucket is half
sorted.

    python -m app.scripts.migrate_storage --relayout           # dry run
    python -m app.scripts.migrate_storage --relayout --apply

Safe to re-run either way: a row already at the key it should have is skipped,
and nothing is deleted until the copy is confirmed written. Verify the bucket,
then delete the disk — never the other way round.
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.attachment import Attachment
from app.services import storage
from app.services.doc_ref import document_ref


def _key_of(storage_path: str) -> str:
    """The part after the bucket, for comparing where a file is with where it goes."""
    if storage_path.startswith(storage.S3_PREFIX):
        return storage_path.split("/", 3)[3] if storage_path.count("/") >= 3 else ""
    return storage_path


async def _wanted_key(db, a: Attachment) -> str:
    """Where `build_key` would put this file today, minus its random prefix."""
    ref = await document_ref(db, a.owner_type, a.owner_id)
    key = storage.build_key(a.filename or "file", owner_type=a.owner_type,
                            owner_id=a.owner_id, owner_ref=ref)
    return key.rsplit("/", 1)[0]          # the folder; the stem is always fresh


async def main() -> None:
    apply = "--apply" in sys.argv
    relayout = "--relayout" in sys.argv

    if settings.STORAGE_BACKEND.lower() != "s3":
        print("STORAGE_BACKEND is not 's3' — set it (and the S3_* credentials) "
              "before migrating, or the files have nowhere to go.")
        return
    if not settings.S3_BUCKET:
        print("S3_BUCKET is not set.")
        return

    print(f"bucket   : {settings.S3_BUCKET}")
    print(f"endpoint : {settings.S3_ENDPOINT_URL or '(aws default)'}")
    print(f"job      : {'re-file bucket objects under document numbers' if relayout else 'copy local files into the bucket'}")
    print(f"mode     : {'APPLY — files will be written' if apply else 'DRY RUN — nothing will change'}")
    print()

    moved = skipped = missing = failed = 0
    async with SessionLocal() as db:
        rows = (await db.scalars(
            select(Attachment).order_by(Attachment.created_at.asc())
        )).all()

        for a in rows:
            path = a.storage_path or ""
            if not path:
                skipped += 1          # link attachment — no file at all
                continue

            in_bucket = path.startswith(storage.S3_PREFIX)
            if relayout:
                if not in_bucket:
                    # Still on disk: the other job moves it, and moving it will
                    # give it today's layout for free.
                    skipped += 1
                    continue
                if _key_of(path).rsplit("/", 1)[0] == await _wanted_key(db, a):
                    skipped += 1      # already where it belongs
                    continue
            elif in_bucket:
                skipped += 1          # already migrated
                continue

            data = await storage.load(path)
            if data is None:
                # Almost certainly a casualty of the old ephemeral /tmp on the
                # Hugging Face Space. Nothing to move; the row stays so the
                # audit trail still shows the file was once attached.
                print(f"  MISSING  {a.filename}  ({path})")
                missing += 1
                continue

            if not apply:
                print(f"  would move  {a.filename}  ->  "
                      f"{await _wanted_key(db, a)}/  ({len(data):,} bytes)")
                moved += 1
                continue

            try:
                new_path = await storage.save(
                    data, filename=a.filename or "file",
                    # Migrated files land in the same organised layout as
                    # new uploads rather than a flat dump — the row knows
                    # what it belongs to, so the key may as well say so.
                    owner_type=a.owner_type, owner_id=a.owner_id, db=db)
                old_path = a.storage_path
                a.storage_path = new_path
                await db.flush()
                print(f"  moved  {a.filename}  ->  {new_path}")
                moved += 1
                if relayout:
                    # Committed first, then the old object goes. A delete
                    # before the row is durably pointing at the copy is how a
                    # re-file loses a file: crash in between and the row still
                    # names a key that is not there any more.
                    await db.commit()
                    await storage.delete(old_path)
            except Exception as exc:      # noqa: BLE001 — report and continue
                print(f"  FAILED   {a.filename}: {exc}")
                failed += 1

        if apply:
            await db.commit()

    print()
    print(f"{'moved' if apply else 'to move'}: {moved}   already-done/links: {skipped}   "
          f"missing: {missing}   failed: {failed}")
    if not apply and moved:
        print("\nRe-run with --apply to perform the copy.")
    if apply and failed:
        print("\nSome files failed — re-run to retry just those; the copy is idempotent.")


if __name__ == "__main__":
    asyncio.run(main())
