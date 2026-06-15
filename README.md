# Whscraper

Scrapes the WH ICE-arrests Flourish geo-map, stores snapshots, diffs them day
over day, emails the changes, and serves a small Flask dashboard.

- `scrape_flourish_map.py` — scrapes the map, writes a JSON snapshot to
  `flourish_data/` and rows into `flourish_data/wh_arrests.db`.
- `daily_check.py` — runs the scrape, diffs the two latest snapshots, emails the
  diff via SendGrid (only when something changed).
- `app.py` — Flask dashboard (`summary`, `/arrests`) served at
  https://wh.stanlee.info.
- `diff_utils.py` — snapshot loading / diffing helpers shared by the above.

---

## Deployment meta (how it all fits together)

```
Internet ──HTTPS──▶ Caddy (:443)  ──reverse_proxy──▶  Gunicorn (127.0.0.1:8000)  ──▶  app.py (Flask)
                    wh.stanlee.info                    (systemd service)

cron (07:00 daily) ──▶  daily_check.py  ──▶  scrape  ──▶  diff  ──▶  SendGrid email
```

Three moving parts on the server:

1. **Gunicorn** runs the Flask app as a long-lived process bound to localhost.
2. **systemd** keeps Gunicorn alive (auto-start on boot, restart on crash).
3. **Caddy** terminates TLS and reverse-proxies the public domain to Gunicorn.
4. **cron** runs the daily scrape + email, independent of the web app.

### 1. Gunicorn

The web server. `app.py` exposes the Flask object as `app`, so the WSGI target is
`app:app`. Gunicorn binds to localhost only — Caddy is the public face.

```bash
# manual test run from the project dir
uv run gunicorn --workers 2 --bind 127.0.0.1:8000 app:app
```

`gunicorn` is pinned in `pyproject.toml`, so `uv run gunicorn ...` resolves it
from the project venv.

### 2. systemd service

Keeps Gunicorn running. The unit lives at `/etc/systemd/system/whscraper.service`
— a copy is version-controlled at [`deploy/whscraper.service`](deploy/whscraper.service):

```ini
[Unit]
Description=Whscraper Flask web app (gunicorn)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/Whscraper
ExecStart=/snap/bin/uv run gunicorn app:app --bind 127.0.0.1:8000 --workers 3
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Deploy the unit:

```bash
sudo cp deploy/whscraper.service /etc/systemd/system/whscraper.service
sudo systemctl daemon-reload
sudo systemctl enable --now whscraper
```

Manage it:

```bash
sudo systemctl daemon-reload          # after editing the unit file
sudo systemctl enable --now whscraper # start now + on boot
sudo systemctl restart whscraper      # after deploying new code
sudo systemctl status whscraper       # health
journalctl -u whscraper -f            # live logs
```

### 3. Caddy

Reverse proxy + automatic HTTPS (Let's Encrypt). `/etc/caddy/Caddyfile`:

```caddyfile
wh.stanlee.info {
    reverse_proxy 127.0.0.1:8000
}
```

That single block is enough — Caddy fetches and renews the TLS cert
automatically as long as the domain's DNS A record points at this server.

```bash
sudo systemctl reload caddy   # after editing the Caddyfile
sudo systemctl status caddy
journalctl -u caddy -f
```

### 4. cron (daily scrape + email)

Runs `daily_check.py` every day at 07:00. The `SENDGRID_API_KEY` is passed
inline because cron has a minimal environment. `crontab -e`:

```cron
0 7 * * * cd ~/Whscraper && SENDGRID_API_KEY='my key' uv run daily_check.py >> ~/Whscraper/whscraper.log 2>&1
```

- `cd ~/Whscraper` — cron starts in `$HOME`; the app uses relative paths
  (`flourish_data/...`), so we must be in the project dir.
- `>> ~/Whscraper/whscraper.log 2>&1` — append stdout + stderr to the log.
- Email only sends when the diff is non-empty (see `daily_check.py`).

---

## Local development

```bash
uv sync                       # install deps from pyproject/uv.lock
uv run app.py                 # dev server on 127.0.0.1:8000 (Flask, not gunicorn)
uv run scrape_flourish_map.py # one-off scrape
SENDGRID_API_KEY='...' uv run daily_check.py  # full scrape + diff + email
```

## Deploying a change

```bash
git pull
uv sync                          # if deps changed
sudo systemctl restart whscraper # pick up new app code
```
