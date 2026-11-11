#!/usr/bin/env bash
# Datenbank-Dump und Uploads nach ./backups, 14 Tage aufbewahrt. Optionales Argument: Kennzeichen im Dateinamen.
# Liegt nur auf demselben Server: Offsite-Kopie (restic, EU-Speicher) ist noch einzurichten.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p backups

stamp="$(date +%Y%m%d-%H%M%S)${1:+-$1}"
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump --single-transaction --no-tablespaces -u "$MYSQL_USER" "$MYSQL_DATABASE"' \
    | gzip > "backups/db-$stamp.sql.gz"
tar -czf "backups/media-$stamp.tar.gz" media

find backups -type f -mtime +14 -delete
echo "Backup: backups/db-$stamp.sql.gz, backups/media-$stamp.tar.gz"
