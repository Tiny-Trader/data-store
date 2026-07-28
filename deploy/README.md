# Deploy (prototype EC2)

Direct Linux + systemd. No Docker / nginx. One Ubuntu box runs the API and the
EOD timer. Cloudflare (optional) can sit in front; origin is gunicorn on `:8000`.

**Host-specific details (IP, SSH alias, key path) are not in this public doc.**
Copy the local template and keep it private:

```bash
cp deploy/host.local.example deploy/host.local   # gitignored — edit with real values
```

See `deploy/host.local.example` for the fields. Commands below assume you
`source deploy/host.local` first (or use your SSH host alias).

## How updates reach the server

Two options. For this prototype we mostly use **A**, because local changes are
often ahead of GitHub.

### A. Rsync from your laptop (default right now)

Copies your working tree over SSH into `/opt/tiny-trader/data-store`, then
installs deps / collects static / restarts the API as needed.

From the **data-store repo root**:

```bash
set -a && source deploy/host.local && set +a
# expects: DEPLOY_HOST (user@host or SSH alias), DEPLOY_KEY (path to .pem)
# optional: DEPLOY_SSH_HOST alias if you prefer `ssh $DEPLOY_SSH_HOST`

# 1) Sync code (does not touch .env, data/, db, or local keys)
rsync -az \
  --exclude '.venv/' \
  --exclude '.git/' \
  --exclude 'data/' \
  --exclude 'logs/' \
  --exclude 'db.sqlite3' \
  --exclude '.env' \
  --exclude 'deploy/keys/' \
  --exclude 'deploy/host.local' \
  --exclude '__pycache__/' \
  --exclude 'staticfiles/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  -e "ssh -i $DEPLOY_KEY -o StrictHostKeyChecking=accept-new" \
  ./ "${DEPLOY_HOST}:/opt/tiny-trader/data-store/"

# 2) On the box: deps + static + restart
ssh -i "$DEPLOY_KEY" "$DEPLOY_HOST" 'export PATH="$HOME/.local/bin:$PATH"
  cd /opt/tiny-trader/data-store
  poetry install --without dev -n
  poetry run python manage.py migrate
  poetry run python manage.py collectstatic --noinput
  sudo systemctl restart tt-api'
```

Or: `./deploy/sync.sh` (same steps; reads `deploy/host.local`).

What each piece does:

| Command | Purpose |
|---------|---------|
| `rsync … ./ host:…/data-store/` | Push local files to the server (excludes secrets + Parquet + DB) |
| `poetry install` | Install/update Python deps from the lockfile |
| `migrate` | Apply Django schema changes |
| `collectstatic` | Copy admin/CSS into `staticfiles/` for WhiteNoise |
| `systemctl restart tt-api` | Reload gunicorn so code/settings take effect |

Skip `migrate` / `collectstatic` if you only changed Python view code with no
schema or static changes — but restart is still required.

### B. Git pull on the server (once changes are on GitHub)

```bash
ssh <your-ssh-alias>          # from host.local / ~/.ssh/config
cd /opt/tiny-trader/data-store
git pull
export PATH="$HOME/.local/bin:$PATH"
poetry install --without dev -n
poetry run python manage.py migrate
poetry run python manage.py collectstatic --noinput
sudo systemctl restart tt-api
```

`git push` alone does **not** update EC2. Something must pull (or you rsync).

## Once: bootstrap

1. Ubuntu 24.04 · `t3a.micro` · EIP · SG (SSH + 8000 from your IP / Cloudflare)
2. apt: `git`, `build-essential`, `python3` (+ venv/dev) — **system 3.12**, not pyenv
3. 2 GB swap (micro is memory-tight)
4. Poetry for `ubuntu`; app under `/opt/tiny-trader/data-store`
5. `tt-connect` via **HTTPS** git URL in `pyproject.toml` (public repo; no deploy key)
6. `.env` on the box only (`DJANGO_DEBUG=false`, `ALLOWED_HOSTS`, `API_KEY`, `PARQUET_ROOT=data`, broker JSON when ready)
7. `migrate` · `seed_watchlist` · `collectstatic`
8. systemd units enabled
9. Fill in `deploy/host.local` + optional `~/.ssh/config` Host entry on your laptop

## systemd

```bash
sudo cp deploy/systemd/tt-api.service \
        deploy/systemd/tt-eod.service \
        deploy/systemd/tt-eod.timer \
        deploy/systemd/tt-backup.service \
        deploy/systemd/tt-backup.timer \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tt-api.service
sudo systemctl enable --now tt-eod.timer
sudo systemctl enable --now tt-backup.timer
```

| Unit | Role |
|------|------|
| `tt-api.service` | gunicorn (gthread) on `:8000` + WhiteNoise for admin CSS |
| `tt-eod.timer` | Mon–Fri 18:30 IST → `sync_eod` |
| `tt-backup.timer` | Mon–Fri 19:00 IST → S3 backup (candles + SQLite) |

Fix Poetry path with `which poetry` if the unit fails to start.

## Backups (S3)

Logical name **tt-dev**; bucket is `tt-dev-tiny-trader` in `ap-south-1` (`tt-dev` alone was already taken globally on S3).

| Prefix | Contents | Retention |
|--------|----------|-----------|
| `data-store/candles/` | Parquet tree (`aws s3 sync`) | Rolling mirror (no expiry) |
| `data-store/catalog/db-YYYY-MM-DD.sqlite3` | SQLite snapshot | **7 days** (bucket lifecycle on `catalog/`) |

Script: `deploy/backup.sh` (optional overrides in gitignored `deploy/backup.env`). EC2 uses instance role `tt-data-store-ec2`.

```bash
sudo systemctl start tt-backup.service
journalctl -u tt-backup.service -n 50
aws s3 ls s3://tt-dev-tiny-trader/data-store/catalog/
```

Restore (sketch): sync candles back into `PARQUET_ROOT/candles/`, copy a `db-*.sqlite3` to `db.sqlite3`, restart `tt-api`.

## Operate

```bash
set -a && source deploy/host.local && set +a

curl "http://${DEPLOY_API_HOST}:8000/api/health/"
curl -H "X-API-Key: $API_KEY" \
  "http://${DEPLOY_API_HOST}:8000/api/candles/?key=NSE:NIFTY:INDEX&interval=day&start=…&end=…"

# EOD (needs TT_*_CONFIG in server .env)
ssh -i "$DEPLOY_KEY" "$DEPLOY_HOST"
systemctl list-timers tt-eod.timer tt-backup.timer
sudo systemctl start tt-eod.service
journalctl -u tt-eod.service -f
```

API key lives in the **server** `.env` (not in git). Optionally mirror
`API_KEY` into `host.local` for local curl convenience only.

## Out of scope (prototype)

Nginx on the box, Docker, RDS, CI. Cloudflare proxy is fine without a local reverse proxy for now.
