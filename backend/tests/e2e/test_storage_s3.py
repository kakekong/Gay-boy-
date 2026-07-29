"""The S3/R2 storage backend, exercised against a real S3 server.

moto is run as an actual HTTP server and pointed at via S3_ENDPOINT_URL — the
same knob Cloudflare R2 uses — so this drives genuine boto3 request signing and
genuine bucket round-trips rather than a mock that agrees with us.

The thing this has to prove is not "uploads work". It is that switching the
backend does not strand what is already stored: a file written to disk before
the flip must still download after it, because that is the entire migration
plan.

Skips itself (as a pass) when moto is not installed, so the suite still runs on
a machine without the dev extra.
"""
import asyncio, os, sys, uuid, threading, socket
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except: return {"_":r.text[:150]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

def free_port():
    s=socket.socket(); s.bind(("127.0.0.1",0)); p=s.getsockname()[1]; s.close(); return p

def start_moto():
    """A real S3 server on localhost. Returns its base URL, or None."""
    try:
        from moto.server import ThreadedMotoServer
    except ImportError:
        return None, None
    port=free_port()
    srv=ThreadedMotoServer(port=port, verbose=False)
    srv.start()
    return srv, f"http://127.0.0.1:{port}"

async def main():
    srv, endpoint = start_moto()
    if endpoint is None:
        print("moto not installed — skipping the S3 backend checks")
        print("\n0 passed, 0 failed")
        return

    BUCKET=f"transmisi-test-{uuid.uuid4().hex[:8]}"
    # R2 wants S3_REGION="auto"; moto emulates AWS and rejects that on
    # CreateBucket, so the local server runs as us-east-1. Everything else —
    # signing, the custom endpoint, the request shape — is identical.
    os.environ.update(S3_ENDPOINT_URL=endpoint, S3_BUCKET=BUCKET, S3_REGION="us-east-1",
                      S3_ACCESS_KEY_ID="test", S3_SECRET_ACCESS_KEY="test",
                      AWS_ACCESS_KEY_ID="test", AWS_SECRET_ACCESS_KEY="test",
                      # boto3 must reach the loopback server directly.
                      NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")

    from app.core.config import get_settings, settings
    get_settings.cache_clear()
    from app.services import storage
    storage._client.cache_clear()
    # Re-read the env into the live settings object the app already imported.
    for k in ("S3_ENDPOINT_URL","S3_BUCKET","S3_REGION","S3_ACCESS_KEY_ID","S3_SECRET_ACCESS_KEY"):
        setattr(settings, k, os.environ[k])

    storage._client().create_bucket(Bucket=BUCKET)
    check("bucket created on the S3 server", True)

    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    H={"d":await login(c,"director@demo.local")}
    tag=uuid.uuid4().hex[:6]
    cust=J(await c.post("/customers",headers=H["d"],json={"company_name":f"PT Storage {tag}","industry":"mining"}))["id"]

    # ---------- 1. a file written while the backend is LOCAL ----------
    settings.STORAGE_BACKEND="local"
    local_body=b"written to disk before the switch"
    r=await c.post("/attachments",headers=H["d"],
                   files={"file":("on-disk.txt",local_body,"text/plain")},
                   data={"owner_type":"customer","owner_id":cust})
    check("upload while local", r.status_code==201, J(r))
    local_id=J(r).get("id")
    from app.core.db import SessionLocal
    from app.models.attachment import Attachment
    async with SessionLocal() as db:
        row=await db.get(Attachment, uuid.UUID(local_id))
        local_path=row.storage_path
    check("local upload stored a filesystem path",
          not local_path.startswith("s3://") and os.path.exists(local_path), local_path)

    # ---------- 2. flip to S3 ----------
    settings.STORAGE_BACKEND="s3"

    s3_body=b"written to the bucket after the switch"
    r=await c.post("/attachments",headers=H["d"],
                   files={"file":("in-bucket.txt",s3_body,"text/plain")},
                   data={"owner_type":"customer","owner_id":cust})
    check("upload while s3", r.status_code==201, J(r))
    s3_id=J(r).get("id")
    async with SessionLocal() as db:
        row=await db.get(Attachment, uuid.UUID(s3_id))
        s3_path=row.storage_path
    check("s3 upload stored an s3:// uri", s3_path.startswith(f"s3://{BUCKET}/"), s3_path)
    check("nothing was written to disk for it", not os.path.exists(s3_path.replace("s3://","")), s3_path)

    # the object is really in the bucket, byte for byte
    key=s3_path.split("/",3)[3]
    got=storage._client().get_object(Bucket=BUCKET,Key=key)["Body"].read()
    check("the bucket holds the exact bytes", got==s3_body, f"{got[:40]!r}")
    check("the key keeps the year/month foldering", key.startswith("attachments/"), key)

    # ---------- 3. THE POINT: the pre-switch file still downloads ----------
    r=await c.get(f"/attachments/{local_id}/download",headers=H["d"])
    check("a file stored BEFORE the switch still downloads after it",
          r.status_code==200 and r.content==local_body, f"{r.status_code} {r.content[:40]!r}")
    r=await c.get(f"/attachments/{s3_id}/download",headers=H["d"])
    check("a file stored after the switch downloads from the bucket",
          r.status_code==200 and r.content==s3_body, f"{r.status_code} {r.content[:40]!r}")
    check("the download carries the original filename",
          'in-bucket.txt' in r.headers.get("content-disposition",""),
          r.headers.get("content-disposition"))

    # ---------- 4. permissions still apply to bucket-backed files ----------
    sales=await login(c,"sales1@demo.local")
    r=await c.get(f"/attachments/{s3_id}/download",headers=sales)
    check("role checks still gate a bucket-backed file (no presigned bypass)",
          r.status_code==403, str(r.status_code))

    # ---------- 5. a vanished object reads as gone, not as a 500 ----------
    storage._client().delete_object(Bucket=BUCKET,Key=key)
    r=await c.get(f"/attachments/{s3_id}/download",headers=H["d"])
    check("an object deleted underneath us returns 410, not 500", r.status_code==410, str(r.status_code))

    # ---------- 6. delete removes the object from the bucket ----------
    r=await c.post("/attachments",headers=H["d"],
                   files={"file":("to-delete.txt",b"bye","text/plain")},
                   data={"owner_type":"customer","owner_id":cust})
    del_id=J(r).get("id")
    async with SessionLocal() as db:
        row=await db.get(Attachment, uuid.UUID(del_id))
        del_key=row.storage_path.split("/",3)[3]
    r=await c.delete(f"/attachments/{del_id}",headers=H["d"])
    check("delete returns 204", r.status_code==204, str(r.status_code))
    listing=storage._client().list_objects_v2(Bucket=BUCKET,Prefix=del_key).get("KeyCount",0)
    check("the object is gone from the bucket too", listing==0, f"KeyCount={listing}")

    # ---------- 7. the migration script moves the old disk file across ----------
    from app.scripts.migrate_storage import main as migrate
    await migrate()                      # dry run — must not change anything
    async with SessionLocal() as db:
        row=await db.get(Attachment, uuid.UUID(local_id))
        check("dry run leaves the row alone", row.storage_path==local_path, row.storage_path)
    sys.argv.append("--apply")
    await migrate()
    sys.argv.remove("--apply")
    async with SessionLocal() as db:
        db.expire_all()
        row=await db.get(Attachment, uuid.UUID(local_id))
        migrated=row.storage_path
    check("--apply rewrote the row to the bucket", migrated.startswith(f"s3://{BUCKET}/"), migrated)
    r=await c.get(f"/attachments/{local_id}/download",headers=H["d"])
    check("the migrated file downloads with its original bytes",
          r.status_code==200 and r.content==local_body, f"{r.status_code} {r.content[:40]!r}")

    await c.aclose()
    settings.STORAGE_BACKEND="local"
    if srv: srv.stop()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)

asyncio.run(main())
