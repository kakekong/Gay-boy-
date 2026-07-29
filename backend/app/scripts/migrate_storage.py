"""Copy attachments already on local disk into the S3/R2 bucket.

Not needed to *switch* backends — reads follow whatever path each row stores,
so flipping `STORAGE_BACKEND=s3` works immediately and old files keep serving
off the disk. This is for afterwards, when you want to detach the disk.

    # see what would move, touch nothing
    python -m app.scripts.migrate_storage

    # actually do it
    python -m app.scripts.migrate_storage --apply

Safe to re-run: rows already pointing at `s3://` are skipped, and the local
file is left alone. Verify the bucket, then delete the disk — never the other
way round.
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.attachment import Attachment
from app.services import storage


async def main() -> None:
    apply = "--apply" in sys.argv

    if settings.STORAGE_BACKEND.lower() != "s3":
        print("STORAGE_BACKEND is not 's3' — set it (and the S3_* credentials) "
              "before migrating, or the files have nowhere to go.")
        return
    if not settings.S3_BUCKET:
        print("S3_BUCKET is not set.")
        return

    print(f"bucket   : {settings.S3_BUCKET}")
    print(f"endpoint : {settings.S3_ENDPOINT_URL or '(aws default)'}")
    print(f"mode     : {'APPLY — files will be uploaded' if apply else 'DRY RUN — nothing will change'}")
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
            if path.startswith(storage.S3_PREFIX):
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
                print(f"  would move  {a.filename}  ({len(data):,} bytes)")
                moved += 1
                continue

            try:
                new_path = await storage.save(data, filename=a.filename or "file")
                a.storage_path = new_path
                await db.flush()
                print(f"  moved  {a.filename}  ->  {new_path}")
                moved += 1
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
