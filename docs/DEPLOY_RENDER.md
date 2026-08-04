# Deploying the backend to Render

Moving the API off the Hugging Face Space onto Render. Two things get fixed by
the move:

- **Uploaded files stop disappearing.** They go to a Cloudflare R2 bucket
  instead of the Space's `/tmp`, which was wiped on every rebuild.
- **No more manual rebuilds.** Render redeploys on every push, the way Vercel
  already does for the frontend.

The database does **not** move. Neon stays exactly as it is.

Two accounts to set up: **Cloudflare** (the bucket — do this first, it takes
five minutes and Render needs its credentials) and **Render** (the API itself).
Budget about 45 minutes, most of it waiting on the first build.

---

## Before you start

Have these to hand:

| Thing | Where to get it |
|---|---|
| The `DATABASE_URL` value | Your own notes, or rebuilt from Neon — see the warning below |
| Your site's domain(s) | `https://transmisisuplindo.com` (and the `www.` variant if you use it) |
| Four R2 values | From step 0 below |
| `OPENAI_API_KEY` | Only if you use the AI features. Optional |

> **`DATABASE_URL` needs two edits, and you cannot read it back off the Space.**
>
> Hugging Face secrets are write-only — the Settings page offers *Replace* and
> *Delete*, never *View* — so the working value is only recoverable from wherever
> you saved it when you first set it up.
>
> Failing that, rebuild it from Neon's dashboard. Neon's copy button gives you:
>
> ```
> postgresql://user:password@ep-xxx.aws.neon.tech/dbname?sslmode=require
> ```
>
> Change `postgresql://` to `postgresql+asyncpg://`, and delete `?sslmode=require`
> and anything after it:
>
> ```
> postgresql+asyncpg://user:password@ep-xxx.aws.neon.tech/dbname
> ```
>
> A quick way to tell you have the right one: hitting the service root returns
> `{"data":null,"errors":[{"code":"NOT_FOUND",…}],"meta":null}`. That is the
> app's own error envelope, so seeing it means FastAPI booted and reached the
> database — the root path simply has no route. A database failure looks
> nothing like it.
>
> Both edits matter. The scheme selects the async driver, and `sslmode` is not a
> keyword `asyncpg` accepts — leaving it in raises
> `connect() got an unexpected keyword argument 'sslmode'` on the first query.
> TLS still happens regardless: asyncpg negotiates it because Neon requires it.

---

## 0. Create the R2 bucket (do this first)

Render needs these credentials during setup, so make them before you start
there.

1. Sign in to Cloudflare → **R2 Object Storage**. It asks for a payment card
   even on the free tier; the free allowance is 10 GB of storage per month,
   which covers roughly your first year.
2. **Create bucket**. Name it something like `transmisi-files`. Location:
   **Asia-Pacific** if offered. Leave it **private** — the app streams files
   through the API after checking permissions, and a public bucket would hand
   out customer documents to anyone with the URL.
3. On the R2 overview page, copy the **S3 API endpoint**. It looks like
   `https://<account-id>.r2.cloudflarestorage.com`. That is `S3_ENDPOINT_URL`.
4. **Manage R2 API Tokens → Create API token**. Permission **Object Read &
   Write**, scoped to just that bucket. Create it.
5. Copy the **Access Key ID** and **Secret Access Key** now. The secret is shown
   **once** and cannot be retrieved later — if you lose it, delete the token and
   make another.

You now have the four values Render asks for:

| Key | Example |
|---|---|
| `S3_ENDPOINT_URL` | `https://abc123….r2.cloudflarestorage.com` |
| `S3_BUCKET` | `transmisi-files` |
| `S3_ACCESS_KEY_ID` | from the API token |
| `S3_SECRET_ACCESS_KEY` | from the API token |

**Leave the bucket name off `S3_ENDPOINT_URL`.** Cloudflare shows it as
`https://<account-id>.r2.cloudflarestorage.com/transmisi-files`, but boto3
appends the bucket itself, so keeping it produces
`…/transmisi-files/transmisi-files/attachments/…`. Worse, that still returns
HTTP 200 — uploads appear to work and quietly land in a nested folder. Take
only the host part.

Ignore anything Cloudflare says about public bucket URLs or custom domains for
R2 — the app never uses them.

## 1. Create the service

1. Sign in to Render.
2. **New → Blueprint**.
3. Connect GitHub and grant access to `kakekong/Gay-boy-` when prompted.
4. Pick the repo, and set the branch to **`claude/enterprise-crm-erp-ai-IMGRg`**.
5. Render finds `render.yaml` at the repo root and shows one service,
   `transmisi-api`. Approve it.

It will then ask for the values marked "sync: false" in the blueprint. That's
step 2.

## 2. Paste the secrets

| Key | Value |
|---|---|
| `DATABASE_URL` | the value copied from the Space, unchanged |
| `CORS_ORIGINS` | `["https://transmisisuplindo.com","https://www.transmisisuplindo.com"]` |
| `S3_ENDPOINT_URL` | from step 0 |
| `S3_BUCKET` | from step 0 |
| `S3_ACCESS_KEY_ID` | from step 0 |
| `S3_SECRET_ACCESS_KEY` | from step 0 |
| `OPENAI_API_KEY` | your key, or leave blank |

`CORS_ORIGINS` **must be a JSON array**, square brackets and double quotes
included, exactly as written above. A bare domain will not parse. Include every
domain the site is served from — if a browser loads the app from an origin that
isn't in this list, every API call fails.

`JWT_SECRET` and `N8N_WEBHOOK_SECRET` are generated by Render automatically.
You never need to see them. Because the new `JWT_SECRET` differs from the
Space's, **everyone is signed out once at cutover** and simply logs back in —
expected, not a fault. Don't rotate it later on a whim; it has the same effect
every time.

Nothing else needs carrying over from the Space. `DATABASE_SYNC_URL` and
`REDIS_URL` are declared in `app/core/config.py` but read nowhere at runtime
(Celery is never imported at boot), and `STORAGE_LOCAL_DIR` is moot now that
files go to R2.

## 3. Deploy and watch the log

Click deploy. The first build takes several minutes because it compiles the
Python dependencies; later ones are much faster thanks to layer caching.

In the log, look for this sequence:

```
[boot] database schema check (attempt 1/3)…
[boot] schema ready — starting API.
[boot] web-push sweeper started.
Uvicorn running on http://0.0.0.0:10000
```

If instead you see **`Refusing to start in APP_ENV=prod with insecure
defaults`**, the app is telling you exactly which variable is still wrong —
read the list it prints and fix that one.

If it hangs on the schema check, Neon is asleep. It wakes on its own; the app
retries three times and starts anyway.

## 4. Check it before switching anything over

The live service is **`https://transmisi-api.onrender.com`** (the bucket is
`transmisi-files`).

Open `https://transmisi-api.onrender.com/healthz` in a browser. You should see:

```json
{"status": "ok"}
```

That is the same endpoint Render polls to decide the service is alive, so if
this works, the deploy is good.

## 5. Point the frontend at it

In **Vercel → your project → Settings → Environment Variables**:

```
VITE_API_BASE = https://transmisi-api.onrender.com/api/v1
```

Note the `/api/v1` on the end — it is part of the value, not optional.

Redeploy the frontend for the change to take effect. Vite bakes environment
variables in at build time, so an existing deployment will keep talking to the
old backend until you rebuild it.

## 6. Confirm the file problem is actually fixed

This is the part worth doing properly, because it is the reason for the move:

1. Log in to the live site and upload a file somewhere — an attachment on a
   customer, or a drawing on a project.
2. Check it appeared: Cloudflare → your bucket → you should see it under
   `attachments/<what it belongs to>/<year>/<month>/<the document>/`, e.g.
   `attachments/customer_po/2026/08/<po-id>/c9e9425a_po-scan.pdf`. Everything
   attached to one document shares that folder, so the prefix is that
   document's file list.

   Files uploaded before August 2026 sit under the older, flatter
   `attachments/<year>/<month>/` instead. That is expected and harmless — each
   database row stores its own full key and downloads follow it, so old and
   new files serve identically. Nothing needs migrating.
3. In Render, hit **Manual Deploy → Deploy latest commit**.
4. When it comes back up, open that file again.

On the old Space it would 404. It should now download exactly as before.

If the upload fails instead, the R2 credentials are wrong — check the Render
log for the error, fix the four `S3_*` values, and redeploy. Nothing else in
the app is affected while you sort it out.

## 7. Retire the Space

Only once everything above passes. Keep the Space around, paused, for a week or
so in case you want to fall back — it costs nothing sitting idle, and the code
to run it (`infra/hfspace/Dockerfile`) stays in the repo either way.

---

## Things worth knowing

**What this costs.** $7/month for the Render service, and R2 is free until the
bucket passes 10 GB — then roughly $0.015/GB/month with no charge for
downloads. At about 10 GB of attachments a year, storage stays near zero for a
long time. A Render persistent disk would have been $0.25/GB/month, or 16×
more, and would also have forbidden zero-downtime deploys and any future
scaling.

**Why there is no disk.** Nothing is stored on the instance, so Render is free
to start the new container before stopping the old one, and you could run more
than one instance later if the load ever justified it. Neither is possible with
a disk attached.

**If you would rather start on a disk anyway.** The code still supports it —
leave `STORAGE_BACKEND` unset (it defaults to `local`), drop the four `S3_*`
variables, and add a disk to `render.yaml`:

```yaml
    disk:
      name: storage
      mountPath: /data
      sizeGB: 15
```

with `STORAGE_LOCAL_DIR=/data/storage`. You can move to R2 later without
downtime — see the next note.

**Switching backends is not a cliff.** Every file download follows the path
stored on its own database row, not the current setting. So flipping
`STORAGE_BACKEND` to `s3` takes effect for new uploads immediately while
everything uploaded before it keeps serving from wherever it already lives.
When you want to consolidate, run the migration once:

```bash
python -m app.scripts.migrate_storage           # dry run, changes nothing
python -m app.scripts.migrate_storage --apply   # copies files, rewrites rows
```

It is idempotent — rows already on R2 are skipped, so a re-run is safe. Files
that vanished with an old Space rebuild are reported as `MISSING` and their
rows left alone, so the audit trail still shows something was once attached.

**Instance size.** Starter (512 MB RAM, 0.5 CPU) is enough, measured rather
than guessed: the app settles around 150 MB after boot and peaked at 214 MB
while generating a quotation PDF and an Excel export back to back — the
heaviest things it does. That leaves better than 2× headroom. Move up to
Standard only if the Render metrics tab actually shows memory pressure.

**Which branch deploys.** Whatever branch you connected in step 1. This is a
genuine improvement over the Space, where the branch was pinned inside the
Dockerfile and pushing anywhere else silently deployed nothing.

**Demo accounts are not created in production.** `APP_ENV=prod` skips them
deliberately. Real users are managed in Admin → Users. There is a safety net in
the seed: if it ever finds no active director at all, it reactivates them, so a
bad migration can't lock you out of your own system.

---

## Files involved

| File | What it does |
|---|---|
| `render.yaml` | the blueprint — service, region, plan, env vars |
| `backend/app/services/storage.py` | the storage layer — local disk or any S3-compatible bucket |
| `backend/app/scripts/migrate_storage.py` | one-off copy of disk files into the bucket |
| `infra/render/Dockerfile` | the image. Copies the repo Render checked out, rather than cloning from GitHub like the Space version does |
| `backend/.dockerignore` | keeps local caches out of the build context |
| `infra/hfspace/Dockerfile` | the old Space build. Left in place as a fallback |
