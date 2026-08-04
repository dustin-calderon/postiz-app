#!/usr/bin/env bash
# Espejo de los medios de Postiz a Google Drive.
#
# Es el respaldo, no el archivo: nadie lo mira. Existe porque /mnt/seagate no
# tenia NINGUNA copia de seguridad (el backup-daily.sh de las 04:00 solo hace
# volcados de bases de datos), y un disco es un disco.
#
# Se usa `copy`, NO `sync`, a proposito:
#   - `sync` borra en destino lo que falte en origen. Si /mnt/seagate no esta
#     montado, la fuente parece vacia y `sync` se lleva por delante el respaldo
#     entero. `copy` nunca borra.
#   - Para un respaldo, conservar lo que se borro en origen es una virtud, no
#     un defecto: es lo que permite recuperar un borrado accidental.
#
# Destino: se direcciona por ID de carpeta, no por ruta. Asi renombrar carpetas
# en Drive no rompe nada.
#   #POSTIZ/Respaldo tecnico  ->  1RmJokTxS7zRGqAWh76J6EG7oY7grXh6A
set -uo pipefail

ORIGEN=/mnt/seagate/postiz-media
DESTINO_ID=1RmJokTxS7zRGqAWh76J6EG7oY7grXh6A
REMOTO=gdrive-work
LOG=/var/log/postiz-archivo.log
LOCK=/var/lock/postiz-respaldo.lock

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] respaldo: $1" >> "$LOG"; }

# Una sola instancia: la subida inicial puede tardar mas que el intervalo.
exec 9>"$LOCK"
if ! flock -n 9; then
  log "ya hay una copia en ejecucion, salgo"
  exit 0
fi

# GUARDARRAIL 1: el origen tiene que existir y tener contenido.
# Sin esto, un fallo de montaje se traduciria en un respaldo que "funciona" y
# no copia nada, y nadie se enteraria hasta necesitarlo.
if [[ ! -d "$ORIGEN" ]]; then
  log "ERROR: $ORIGEN no existe. ¿Disco sin montar? No se copia nada"
  exit 1
fi
N=$(find "$ORIGEN" -type f 2>/dev/null | wc -l)
if [[ "$N" -eq 0 ]]; then
  log "ERROR: $ORIGEN esta vacio ($N ficheros). ¿Disco sin montar? No se copia nada"
  exit 1
fi

# GUARDARRAIL 2: el remoto tiene que responder ANTES de intentar copiar.
if ! rclone lsf --drive-root-folder-id "$DESTINO_ID" "$REMOTO:" >/dev/null 2>&1; then
  log "ERROR: el remoto $REMOTO no responde o no ve la carpeta destino"
  exit 1
fi

ANTES=$(rclone size --json --drive-root-folder-id "$DESTINO_ID" "$REMOTO:" 2>/dev/null \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["count"])' 2>/dev/null || echo 0)

log "empiezo: $N ficheros en origen, $ANTES en destino"

rclone copy "$ORIGEN" "$REMOTO:" \
  --drive-root-folder-id "$DESTINO_ID" \
  --transfers 4 --checkers 8 \
  --drive-chunk-size 32M \
  --log-level INFO --log-file "$LOG" \
  --stats 0
RC=$?

DESPUES=$(rclone size --json --drive-root-folder-id "$DESTINO_ID" "$REMOTO:" 2>/dev/null \
          | python3 -c 'import sys,json;print(json.load(sys.stdin)["count"])' 2>/dev/null || echo 0)

if [[ $RC -eq 0 ]]; then
  log "terminado: $DESPUES ficheros en destino (+$((DESPUES - ANTES)))"
else
  log "ERROR: rclone salio con codigo $RC. Destino: $DESPUES ficheros"
fi

# VERIFICACION: que rclone salga con 0 no prueba que este todo. Se comprueba
# que en destino haya al menos tantos ficheros como en origen (puede haber mas:
# `copy` conserva lo que se borro del disco, que es justo lo que queremos).
if [[ "$DESPUES" -lt "$N" ]]; then
  log "AVISO: destino ($DESPUES) tiene MENOS ficheros que origen ($N). Revisar"
  exit 1
fi

exit $RC
