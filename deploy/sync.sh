#!/bin/sh
# Sync local tree to the EC2 box and restart the API.
# Requires deploy/host.local (see host.local.example).
set -eu
cd "$(dirname "$0")/.."

if [ ! -f deploy/host.local ]; then
  echo "missing deploy/host.local — copy from deploy/host.local.example" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. deploy/host.local
set +a

: "${DEPLOY_HOST:?set DEPLOY_HOST in deploy/host.local}"
: "${DEPLOY_KEY:?set DEPLOY_KEY in deploy/host.local}"

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
  -e "ssh -i ${DEPLOY_KEY} -o StrictHostKeyChecking=accept-new" \
  ./ "${DEPLOY_HOST}:/opt/tiny-trader/data-store/"

ssh -i "${DEPLOY_KEY}" "${DEPLOY_HOST}" 'export PATH="$HOME/.local/bin:$PATH"
  cd /opt/tiny-trader/data-store
  poetry install --without dev -n
  poetry run python manage.py migrate
  poetry run python manage.py collectstatic --noinput
  sudo systemctl restart tt-api'

echo "synced → ${DEPLOY_HOST}"
