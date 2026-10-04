#!/usr/bin/env bash
# Daily backup of everything a receipt needs to stay verifiable:
# the MySQL database AND the blockchain data, always taken together,
# plus uploaded screenshots and receipt PDFs.
#
# Schedule it (as root):   sudo crontab -e
#   30 2 * * * /srv/ledgerfolio/deploy/backup.sh >> /var/log/ledgerfolio-backup.log 2>&1
#
# MySQL credentials are read from /root/.my.cnf, never written in this file:
#   [mysqldump]
#   user=ledgerfolio
#   password=...
#
# The issuer private key is NOT included on purpose. Back it up separately,
# somewhere offline (for example an encrypted USB drive).

set -euo pipefail

APP=/srv/ledgerfolio
DEST=/var/backups/ledgerfolio
KEEP_DAYS=14
STAMP=$(date +%Y-%m-%d_%H%M)

mkdir -p "$DEST"
chmod 700 "$DEST"

# --no-tablespaces: MySQL 8 otherwise needs the PROCESS privilege, which the app user lacks.
mysqldump --no-tablespaces --single-transaction --routines --triggers ledgerfolio | gzip > "$DEST/db_$STAMP.sql.gz"
tar -czf "$DEST/files_$STAMP.tar.gz" -C "$APP" chain_data media private_media

find "$DEST" -type f -mtime +"$KEEP_DAYS" -delete
echo "$(date -Is) backup written to $DEST"

# A backup on the same server is lost with the server. Copy it off, e.g. with
# rclone to cloud storage (run `rclone config` once to set up "offsite"):
# rclone copy "$DEST" offsite:ledgerfolio-backups --max-age 25h
