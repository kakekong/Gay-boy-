# Installation Guide — for absolute beginners

> **No coding experience required.** If you can copy text, paste it into a black
> window, and press Enter, you can do this. Each step explains what's happening
> and why.
>
> Total time: **30–45 minutes** the first time.

---

## What you'll have at the end

A working website at **`http://localhost:5173`** with:
- Demo customers, demo users, demo dashboards
- A working AI Command Center
- A working approvals + WhatsApp pipeline (WhatsApp keys come later, optional)

You can run this:
- 🖥️ **On your own laptop** (Mac, Windows, or Linux) — easiest for trying it out
- ☁️ **On a cloud server** (e.g. DigitalOcean, AWS, Hetzner) — for production

This guide covers **the laptop install first** (try-it-out), then a short
section for **cloud production**.

---

## Part 1 — Try it on your laptop

### Step 1. Install Docker Desktop (the only thing you need)

Docker is a free tool that runs the whole system in little containers, so you
don't have to install Python, PostgreSQL, Node, etc. by hand.

| Operating system | What to do |
|---|---|
| 🍎 **macOS** | Go to <https://www.docker.com/products/docker-desktop> → "Download for Mac". Open the `.dmg` and drag Docker into Applications. Open it from Launchpad. |
| 🪟 **Windows 10/11** | Go to <https://www.docker.com/products/docker-desktop> → "Download for Windows". Run the installer. Restart your PC if it asks. |
| 🐧 **Linux (Ubuntu/Debian)** | Run: `curl -fsSL https://get.docker.com \| sh` then `sudo usermod -aG docker $USER` and log out / back in. |

**Verify it works.** Open a terminal:
- Mac: press `⌘ + space`, type `Terminal`, press Enter
- Windows: press the Windows key, type `PowerShell`, press Enter
- Linux: open your terminal app

Then type:
```bash
docker --version
```

You should see something like `Docker version 27.x.x …`. If not, restart your
computer and try again.

> 💡 On Windows, after installing Docker Desktop, **open the Docker Desktop
> app once** (double-click the whale icon) and wait until it says "Docker is
> running" in the bottom-left corner. Leave it open while you follow the rest
> of this guide.

---

### Step 2. Install Git (if you don't have it)

Git is what we use to download the code.

- **macOS**: open Terminal and type `git --version`. If macOS asks to install
  Xcode tools, click "Install" and wait.
- **Windows**: download from <https://git-scm.com/download/win> and run the
  installer (defaults are fine).
- **Linux**: `sudo apt install -y git`

Verify:
```bash
git --version
```

---

### Step 3. Download the code

In your terminal, navigate to where you want to keep the project (your home
folder is fine), then run:

```bash
git clone https://github.com/kakekong/Gay-boy-.git industriacrm
cd industriacrm
git checkout claude/enterprise-crm-erp-ai-IMGRg
```

That creates a folder called `industriacrm` and switches into it.

> 📁 You can see the files with `ls` (Mac/Linux) or `dir` (Windows). You should
> see `backend`, `frontend`, `docs`, `infra`, `n8n`.

---

### Step 4. Create your settings file

The project ships with an example settings file. You copy it to a real one
called `.env`:

**Mac / Linux:**
```bash
cp infra/.env.example .env
```

**Windows (PowerShell):**
```powershell
copy infra\.env.example .env
```

That's enough for your first try. The file already contains safe demo values.
You'll come back later to add your WhatsApp / OpenAI keys (optional).

---

### Step 5. Start everything with one command

In the same terminal, run:

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
```

**What this does:**
- Downloads PostgreSQL (the database), Redis, n8n (automation engine), and
  Node.js
- Builds the backend and frontend
- Starts all 7 services in the background

The first time, this takes **5–15 minutes** depending on your internet speed.
You'll see lots of text scrolling by — that's normal.

When it's done, run:
```bash
docker compose -f infra/docker-compose.yml ps
```

You should see something like:
```
NAME                        STATUS
infra-api-1                 Up
infra-beat-1                Up
infra-cache-1               Up
infra-db-1                  Up (healthy)
infra-frontend-1            Up
infra-n8n-1                 Up
infra-worker-1              Up
```

If any service says **`Exited`** or **`Restarting`**, jump to **Troubleshooting** below.

---

### Step 6. Set up the database tables

The database is empty. Run this **once** to create the tables and add demo data:

```bash
docker compose -f infra/docker-compose.yml exec api python -m app.scripts.seed
```

The script creates the schema if it's missing and inserts demo users + demo
customers. It's safe to re-run — tables are only created if they don't exist
and users are only inserted if they aren't there yet.

You should see:
```
Schema ready.
Seed complete. Login with director@demo.local / demo1234 etc.
```

> 💡 **Note for ongoing changes:** as the schema evolves you'll switch to
> Alembic migrations (`alembic revision --autogenerate -m "..."` then
> `alembic upgrade head`). The seed script is just for the first-run
> bootstrap.

---

### Step 7. Open it in your browser

Open these in tabs:

| What | URL |
|---|---|
| 🖥️ The app | <http://localhost:5173> |
| 📘 API docs (technical) | <http://localhost:8000/docs> |
| ⚙️ n8n automation editor | <http://localhost:5678> |

Log in with one of these demo accounts:

| Role | Email | Password |
|---|---|---|
| Director (sees everything) | `director@demo.local` | `demo1234` |
| Manager | `manager@demo.local` | `demo1234` |
| Sales | `sales1@demo.local` | `demo1234` |
| Admin | `admin@demo.local` | `demo1234` |

🎉 **You're done.** Click around, try the AI Command Center, log in as
different roles to see different views.

---

### Daily commands

Once installed, you don't need to install anything again. Just:

```bash
# Start everything
docker compose -f infra/docker-compose.yml --env-file .env up -d

# Stop everything
docker compose -f infra/docker-compose.yml down

# See logs (helpful when something is broken)
docker compose -f infra/docker-compose.yml logs -f api

# Restart just the API after a code change
docker compose -f infra/docker-compose.yml restart api
```

---

## Part 2 — Adding your real keys (optional)

Open the `.env` file in a text editor (Notepad, TextEdit, VS Code — anything).
You'll see lines like:

```
OPENAI_API_KEY=
WA_TOKEN=
WA_PHONE_ID=
```

Fill these in to enable the real AI and WhatsApp:

### 🔑 OpenAI (for the AI features)
1. Go to <https://platform.openai.com/api-keys>
2. Click "Create new secret key"
3. Copy it (looks like `sk-…`)
4. Paste into `.env`:
   ```
   OPENAI_API_KEY=sk-your-key-here
   ```
5. Save the file
6. Restart: `docker compose -f infra/docker-compose.yml restart api worker`

> Without a key, the AI features still work — they just return placeholder
> stubs instead of real LLM responses.

### 📱 WhatsApp Cloud API
1. Create a Meta for Developers account: <https://developers.facebook.com>
2. Create an app → add "WhatsApp" product
3. Get the **temporary access token** and **Phone Number ID**
4. Paste into `.env`:
   ```
   WA_TOKEN=EAAG...
   WA_PHONE_ID=1234567890
   ```
5. Restart the n8n service: `docker compose -f infra/docker-compose.yml restart n8n`
6. In the n8n UI (<http://localhost:5678>), import the workflows from `n8n/workflows/`
   and activate them.

> WhatsApp setup is its own adventure. Meta's official guide:
> <https://developers.facebook.com/docs/whatsapp/cloud-api>

---

## Part 3 — Putting it on a real server (production)

For your team to use this from anywhere, you need a small cloud server.

### Recommended setup (cheapest path)

| Item | Recommendation | Why |
|---|---|---|
| Server | **Hetzner CX22** (~€4/mo) or **DigitalOcean $12/mo droplet** | Plenty for 5–20 users |
| OS | **Ubuntu 24.04 LTS** | Easy + well-documented |
| Domain | **Namecheap / Cloudflare** (~$10/yr) | e.g. `crm.yourcompany.com` |
| TLS / HTTPS | **Let's Encrypt** (free) | Already wired in our nginx config |

### Production install — 8 steps

1. **Create the server.** In your cloud provider's panel, create an Ubuntu
   24.04 server with at least **2 GB RAM**. Note the IP address.

2. **Point your domain at it.** In your domain registrar's DNS settings, add an
   A record:
   - Name: `crm` (or whatever subdomain you want)
   - Value: your server's IP address

3. **SSH into the server:**
   ```bash
   ssh root@YOUR_SERVER_IP
   ```

4. **Install Docker:**
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```

5. **Get the code & configure:**
   ```bash
   git clone https://github.com/kakekong/Gay-boy-.git industriacrm
   cd industriacrm
   git checkout claude/enterprise-crm-erp-ai-IMGRg
   cp infra/.env.example .env
   nano .env   # change passwords and JWT_SECRET to something long & random
   ```

   **Important values to change:**
   - `POSTGRES_PASSWORD` — set a strong random password
   - `JWT_SECRET` — set a 64+ character random string (use `openssl rand -hex 48`)
   - `N8N_WEBHOOK_SECRET` — set another random string
   - `N8N_BASIC_AUTH_PASSWORD` — strong password for the n8n editor
   - `OPENAI_API_KEY`, `WA_TOKEN`, `WA_PHONE_ID` — your real keys

6. **Start the stack:**
   ```bash
   docker compose -f infra/docker-compose.yml --env-file .env up -d --build
   docker compose -f infra/docker-compose.yml exec api alembic upgrade head
   docker compose -f infra/docker-compose.yml exec api python -m app.scripts.seed
   ```

7. **Install nginx + free TLS certificate:**
   ```bash
   apt update && apt install -y nginx certbot python3-certbot-nginx
   cp infra/nginx.conf /etc/nginx/conf.d/industriacrm.conf
   # Edit the file: replace `industriacrm.example.com` with your real domain
   nano /etc/nginx/conf.d/industriacrm.conf
   nginx -t && systemctl reload nginx
   certbot --nginx -d crm.yourcompany.com   # follow the prompts; gets free TLS
   ```

8. **Open it.** Visit `https://crm.yourcompany.com` and log in.

> 🔒 **Change the demo passwords immediately** in production. Log in as
> Director → Settings → Users (or remove demo users entirely with a SQL command).

---

## Troubleshooting

### "command not found: docker"
Docker Desktop isn't running yet. Open it from your applications, wait for it
to say "Docker is running", then try again.

### "permission denied" on Linux
You forgot to add yourself to the docker group:
```bash
sudo usermod -aG docker $USER
```
Then **log out and log back in**.

### A service shows `Exited` in `docker compose ps`
Look at its logs:
```bash
docker compose -f infra/docker-compose.yml logs api
```
The error is usually in the last 20 lines.

Common causes:
- **`alembic` migrations not run yet** → see Step 6
- **Port already in use** → another app is using port 8000 / 5173 / 5432.
  Stop that app or change the port in `infra/docker-compose.yml`.
- **`.env` missing** → make sure you copied `infra/.env.example` to `.env` in
  the project root.

### The website loads but says "Network Error"
The backend isn't ready yet. Wait 30 seconds and refresh. If it persists:
```bash
docker compose -f infra/docker-compose.yml logs api | tail -50
```

### "I broke something, how do I start over?"
This wipes the database and starts fresh:
```bash
docker compose -f infra/docker-compose.yml down -v
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
docker compose -f infra/docker-compose.yml exec api python -m app.scripts.seed
```
The `-v` removes the database volume.

### How do I update to a newer version?
```bash
git pull
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
```

---

## Where to go next

- See what the screens look like → [`docs/04-uiux-design.md`](docs/04-uiux-design.md)
- Set up automations (WhatsApp follow-ups, payment reminders) → [`docs/05-automation-flows.md`](docs/05-automation-flows.md)
- Customize for your company → talk to a developer; start them at [`docs/01-architecture.md`](docs/01-architecture.md)

If you got stuck somewhere, screenshot the terminal and ask your developer —
the logs from `docker compose logs` almost always tell them exactly what to do.
