#!/bin/sh
set -eu
DATA_DIR="${DATA_DIR:-/data}"
BACKUP_DIR="${DATA_DIR}/backups"
mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%d-%H%M%S)
if [ -f "${DATA_DIR}/docofficebot.db" ]; then
  cp "${DATA_DIR}/docofficebot.db" "${BACKUP_DIR}/docofficebot-${STAMP}.db"
fi
# keep last 7 backups
i=0
for f in $(ls -1t "${BACKUP_DIR}"/docofficebot-*.db 2>/dev/null); do
  i=$((i + 1))
  if [ "$i" -gt 7 ]; then
    rm -f "$f"
  fi
done
echo "backup done ${STAMP}"
