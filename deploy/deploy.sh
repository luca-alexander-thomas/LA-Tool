#!/usr/bin/env bash
# Baut und startet die ausgecheckte Version (aufgerufen von deploy/release.sh nach dem Auschecken des Release-Tags).
# Ablauf: Image bauen -> Backup -> migrate -> App starten -> Healthcheck; schlägt er fehl, startet das vorige Image.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "FEHLER: .env fehlt in $PWD (Vorlage: .env.example)"; exit 1; }
mkdir -p media backups
chown 1000:1000 media        # Benutzer "app" im Container
chmod 700 backups

# Voriges Image für den Rollback merken
if docker image inspect la-tool-app:latest >/dev/null 2>&1; then
    docker tag la-tool-app:latest la-tool-app:previous
fi

docker compose build app
docker compose up -d --wait db

# Backup vor der Migration (nur wenn schon eine App lief)
if docker image inspect la-tool-app:previous >/dev/null 2>&1; then
    bash deploy/backup.sh "vor-deploy"
fi

docker compose run --rm app python manage.py migrate --noinput
docker compose up -d --remove-orphans app

echo "Warte auf Healthcheck ..."
status=starting
for _ in $(seq 1 30); do
    status=$(docker inspect --format '{{.State.Health.Status}}' la-tool-app 2>/dev/null || echo missing)
    [ "$status" = healthy ] && break
    sleep 4
done

if [ "$status" != healthy ]; then
    echo "FEHLER: Healthcheck '$status'. Letzte Logs:"
    docker compose logs --tail 50 app || true
    if docker image inspect la-tool-app:previous >/dev/null 2>&1; then
        echo "Rollback auf das vorige Image (Datenbank-Stand bleibt; Dump in backups/)."
        docker tag la-tool-app:previous la-tool-app:latest
        docker compose up -d --no-build app
    fi
    exit 1
fi

# Zeitgesteuerte Aufgaben (systemd-Timer) aus dem Repository einspielen
for unit in deploy/systemd/*; do
    sed "s#@DIR@#$PWD#g" "$unit" > "/etc/systemd/system/$(basename "$unit")"
done
systemctl daemon-reload
for timer in deploy/systemd/*.timer; do
    systemctl enable --now "$(basename "$timer")" >/dev/null
done

docker image prune -f >/dev/null
echo "Deploy erfolgreich: $(git describe --tags --always) ($(git log -1 --format='%h %s'))"
