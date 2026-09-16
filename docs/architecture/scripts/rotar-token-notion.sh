#!/usr/bin/env bash
# rotar-token-notion.sh — pone un token nuevo de la integración de Notion del
# pipeline en los DOS sitios donde vive, y comprueba los dos.
#
# Se ejecuta EN la Beelink, con el token por stdin (nunca como argumento: quedaría
# en el historial y en `ps`). Desde el Mac:
#
#   read -rs "T?Token de Notion: " && echo && printf "%s" "$T" | \
#     ssh dchomeserver "bash /opt/repos/postiz-fork/docs/architecture/scripts/rotar-token-notion.sh"; unset T
#
# Los dos sitios, y quién lee cada uno (§14.4 de CONTENT_PIPELINE_NOTION_POSTIZ.md):
#   1. Credencial de n8n 5rCv9a6s5FyI0swq (cabecera Authorization) → sync, retirada y receptor.
#   2. NOTION_API_KEY en /opt/homeserver/.env → archivador de Drive, pruebas y réplica de carruseles.
# No deja copias: el token viejo ya no sirve y las .bak con secretos son un riesgo.
set -euo pipefail

ENV=/opt/homeserver/.env
CRED=5rCv9a6s5FyI0swq
BASE=186a2405-a123-81dc-832f-000b82a65c0c   # Calendario Social Media

T=$(cat | tr -d "[:space:]")
[[ "$T" =~ ^(ntn_|secret_) ]] || { echo "token vacío o con formato raro" >&2; exit 2; }

probar() {
  curl -s -o /dev/null -w "%{http_code}" -X POST "https://api.notion.com/v1/data_sources/$BASE/query" \
    -H "Authorization: Bearer $1" -H "Notion-Version: 2025-09-03" -H "Content-Type: application/json" -d "{\"page_size\":1}"
}
code=$(probar "$T")
[ "$code" = 200 ] || { echo "el token nuevo no lee la base ($code): ¿está conectada la integración en ··· → Conexiones?" >&2; exit 1; }

printf "%s" "$T" | python3 -c "
import sys, pathlib
t = sys.stdin.read(); p = pathlib.Path(\"$ENV\")
ls = p.read_text().splitlines(True)
i = [n for n, l in enumerate(ls) if l.startswith(\"NOTION_API_KEY=\")]
assert len(i) == 1, \"NOTION_API_KEY tiene que estar exactamente una vez\"
ls[i[0]] = \"NOTION_API_KEY=\" + t + \"\n\"
p.write_text(\"\".join(ls))"

docker exec n8n sh -c "umask 077; n8n export:credentials --id $CRED --decrypted --output=/tmp/cred.json >/dev/null 2>&1"
docker exec n8n cat /tmp/cred.json | T="$T" python3 -c "
import json, os, sys
d = json.load(sys.stdin); c = d[0] if isinstance(d, list) else d
assert c[\"data\"][\"name\"].lower() == \"authorization\", c[\"data\"][\"name\"]
c[\"data\"][\"value\"] = \"Bearer \" + os.environ[\"T\"]
json.dump([c], sys.stdout)" | docker exec -i n8n sh -c "umask 077; cat > /tmp/cred-new.json"
docker exec n8n sh -c "n8n import:credentials --input=/tmp/cred-new.json >/dev/null 2>&1; rm -f /tmp/cred.json /tmp/cred-new.json"

# Comprobación: los dos sitios llevan el token y lee la base.
K=$(grep -E "^NOTION_API_KEY=" "$ENV" | cut -d= -f2-)
V=$(docker exec n8n sh -c "n8n export:credentials --id $CRED --decrypted --output=/tmp/c.json >/dev/null 2>&1; cat /tmp/c.json; rm -f /tmp/c.json" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); c=d[0] if isinstance(d,list) else d; print(c[\"data\"][\"value\"])")
[ "$K" = "$T" ] && [ "$V" = "Bearer $T" ] && [ "$(probar "$K")" = 200 ] \
  && echo "ok: .env y credencial de n8n con el token nuevo; la base responde 200" \
  || { echo "algo no cuadra: revisa .env y la credencial $CRED" >&2; exit 1; }
