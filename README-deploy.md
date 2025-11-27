# Deployment Guide (Railway / Docker / VPS)

## Railway / Render / Heroku (quick)
1. Create a new project on Railway / Render / Heroku.
2. Link GitHub repo (upload this repo).
3. Add environment variables (TG_TOKEN, TG_CHATID).
4. Start deploy — use Procfile in /deploy.

## Docker (local / VPS)
1. Copy repo to server.
2. Fill .env (see /deploy/.env.example)
3. From repo root: `docker-compose -f deploy/docker-compose.yml up -d --build`

## Systemd (Ubuntu VPS)
1. Copy files to `/home/youruser/gay_boy_packet_pro_deploy`
2. Edit `deploy/gorangen.service` to set WorkingDirectory and Environment variables
3. `sudo cp deploy/gorangen.service /etc/systemd/system/gorangen.service`
4. `sudo systemctl daemon-reload`
5. `sudo systemctl enable --now gorangen.service`

## Notes
- TradingView requires HTTPS webhook URL. Railway / Render provide HTTPS out of the box.
- For production, integrate broker API for `place_order()` and secure secrets (use Railway secrets or Docker secrets).
