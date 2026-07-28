#!/bin/sh
# Backup Parquet candles + SQLite catalog to S3.
# Requires: aws CLI, IAM creds (instance role preferred).
#
# Env (optional overrides):
#   BACKUP_BUCKET   default tt-dev-tiny-trader  (S3 name "tt-dev" was taken globally)
#   BACKUP_PREFIX   default data-store
#   APP_ROOT        default /opt/tiny-trader/data-store
set -eu

# Optional local overrides (gitignored).
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
if [ -f "${SCRIPT_DIR}/backup.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${SCRIPT_DIR}/backup.env"
  set +a
fi

APP_ROOT="${APP_ROOT:-/opt/tiny-trader/data-store}"
BACKUP_BUCKET="${BACKUP_BUCKET:-tt-dev-tiny-trader}"
BACKUP_PREFIX="${BACKUP_PREFIX:-data-store}"
AWS_REGION="${AWS_DEFAULT_REGION:-ap-south-1}"

CANDLES_DIR="${APP_ROOT}/data/candles"
DB_PATH="${APP_ROOT}/db.sqlite3"
STAMP="$(TZ=Asia/Kolkata date +%Y-%m-%d)"
TMP_DB="$(mktemp "${TMPDIR:-/tmp}/tt-db.XXXXXX.sqlite3")"

cleanup() { rm -f "$TMP_DB"; }
trap cleanup EXIT

export AWS_DEFAULT_REGION="$AWS_REGION"

echo "backup → s3://${BACKUP_BUCKET}/${BACKUP_PREFIX}/  (${STAMP})"

if [ -d "$CANDLES_DIR" ]; then
  aws s3 sync "$CANDLES_DIR/" "s3://${BACKUP_BUCKET}/${BACKUP_PREFIX}/candles/" \
    --region "$AWS_REGION" \
    --only-show-errors
else
  echo "warn: missing candles dir $CANDLES_DIR" >&2
fi

if [ -f "$DB_PATH" ]; then
  # Consistent snapshot without stopping the API (SQLite online backup).
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '$TMP_DB'"
  else
    cp -a "$DB_PATH" "$TMP_DB"
  fi
  aws s3 cp "$TMP_DB" \
    "s3://${BACKUP_BUCKET}/${BACKUP_PREFIX}/catalog/db-${STAMP}.sqlite3" \
    --region "$AWS_REGION" \
    --only-show-errors
else
  echo "warn: missing db $DB_PATH" >&2
fi

echo "backup done"
