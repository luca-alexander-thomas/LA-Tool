#!/usr/bin/env bash
# Rollt ein GitHub-Release aus: Tag auschecken, release.json schreiben, deploy.sh ausführen.
# Aufruf (macht der Deploy-Workflow): deploy/release.sh <tag> <release-json-base64>
# Von Hand ohne Release-Daten: deploy/release.sh <tag>  (release.json enthält dann nur den Tag)
set -euo pipefail
cd "$(dirname "$0")/.."

tag="${1:?Tag fehlt}"
if ! printf '%s' "$tag" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'; then
    echo "FEHLER: ungültiger Tag '$tag'"; exit 1
fi

git fetch --force --tags origin
git checkout --detach "refs/tags/$tag"

if [ -n "${2:-}" ]; then
    printf '%s' "$2" | base64 -d > release.json.tmp
    python3 -c 'import json,sys; json.load(open(sys.argv[1]))' release.json.tmp   # muss gültiges JSON sein
    mv release.json.tmp release.json
else
    printf '{"tag": "%s"}\n' "$tag" > release.json
fi

bash deploy/deploy.sh
