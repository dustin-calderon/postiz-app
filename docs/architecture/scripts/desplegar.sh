#!/bin/bash
# Despliega en el Beelink lo que haya en origin/custom/postiz-dc, y si el
# contenedor nuevo no queda sano, vuelve solo a la imagen que corría.
#
#   desplegar.sh                    despliega el último commit de la rama
#   desplegar.sh --si-hay-cambios   solo si cambió algo que entra en la imagen
#                                   (lo que lanza el cron cada 10 minutos)
#
# Fusionar a custom/postiz-dc es el GO: la rama la protege la puerta del CI, y
# lo que llega a ella se despliega aquí. El detalle y la vuelta atrás a mano,
# en docs/architecture/ARRANQUE_Y_SUPERVISION.md, «Despliegue».
#
# Copia viva: /opt/homeserver/postiz/desplegar.sh. Es una copia, y no el script
# del clon, para que un push al repo no pueda ejecutar nada en el host sin que
# alguien lo copie. Al desplegar se comparan las copias vivas con las del commit
# y el aviso dice si difieren.
#
# Avisa por el bus de Instalar-Home-Server: un fallo se diagnostica en el
# triage, y un despliegue bueno solo se cuenta por Telegram.

set -euo pipefail

# Las rutas y los tiempos se pueden cambiar por entorno solo para
# test_desplegar.sh, que lo prueba entero con un docker de mentira.
REPO=${DESPLEGAR_REPO:-/opt/repos/postiz-fork}
RAMA=custom/postiz-dc
DIR=${DESPLEGAR_DIR:-/opt/homeserver/postiz}
COMPOSE="$DIR/docker-compose.yml"
OPS=${DESPLEGAR_OPS:-/opt/repos/instalar-home-server/server/ops}
ALERTAR="$OPS/alertar.sh"
VOLCAR="$OPS/backup/volcar-app.sh"
VOLCADOS=${DESPLEGAR_VOLCADOS:-/opt/homeserver/ops/volcados-actualizacion}
ESPERA_MAX=${DESPLEGAR_ESPERA_MAX:-600}   # s para quedar sano; el healthcheck da 120 de arranque
PAUSA=${DESPLEGAR_PAUSA:-15}
# El último commit que falló. El cron no lo reintenta: una imagen que no arranca
# tumbaría Postiz cada 10 minutos, y un build roto se repetiría con su aviso.
FALLIDO="$DIR/.desplegar-fallido"

log() { echo "[$(date '+%F %T')] $*"; }

exec 9>"$DIR/.desplegar.lock"
flock -n 9 || { log "ya hay un despliegue en marcha"; exit 0; }

git -C "$REPO" fetch -q origin "$RAMA"
OBJETIVO=$(git -C "$REPO" rev-parse --short "origin/$RAMA")
ANTERIOR=$(docker inspect -f '{{.Config.Image}}' postiz | sed -nE 's|^postiz-custom:||p')
CORRE=${ANTERIOR#local-}

if [ "${1:-}" = "--si-hay-cambios" ]; then
  [ "$CORRE" = "$OBJETIVO" ] && exit 0
  [ "$(cat "$FALLIDO" 2>/dev/null)" = "$OBJETIVO" ] && exit 0
  # Lo que no cambia el código que corre no justifica reiniciar Postiz. Si el
  # commit que corre no está en el historial, se despliega: no se puede saber.
  if git -C "$REPO" cat-file -e "$CORRE^{commit}" 2>/dev/null &&
     git -C "$REPO" diff --quiet "$CORRE" "origin/$RAMA" -- . \
       ':!docs' ':!.fork' ':!.github' ':!*.md'; then
    exit 0
  fi
fi

fallo() {
  log "FALLO: $1"
  echo "$OBJETIVO" > "$FALLIDO"
  "$ALERTAR" --stdin postiz-despliegue <<EOF
🔴 Postiz: el despliegue de $OBJETIVO falló
$1
El cron no lo reintenta: lo hará con el próximo commit, o a mano con $DIR/desplegar.sh.
Log: /opt/homeserver/ops/desplegar-postiz.log
EOF
  exit 1
}

log "desplegando $OBJETIVO (corre $ANTERIOR)"
git -C "$REPO" merge -q --ff-only "origin/$RAMA" ||
  fallo "El clon $REPO no avanza en fast-forward hasta origin/$RAMA: tiene cambios propios."

bash "$DIR/build.sh" || fallo "build.sh falló: la imagen no se construyó y sigue corriendo $ANTERIOR."
NUEVA=local-$OBJETIVO

# El arranque aplica el esquema con `prisma db push`: volver a la imagen
# anterior no deshace un cambio de esquema, este volcado sí. Se queda.
VOLCADO="$VOLCADOS/postiz-$(date +%F-%H%M).dump"
"$VOLCAR" postiz > "$VOLCADO" || fallo "No se pudo volcar la base: no se despliega."

sano_desde() {
  # Sano = el healthcheck (nginx y backend) en verde, las tres apps de pm2
  # online, el frontend contestando por nginx, y el orchestrator de ESTE
  # contenedor escuchando la cola de Temporal.
  local inicio=$1 fin=$(( $(date +%s) + ESPERA_MAX ))
  while [ "$(date +%s)" -lt "$fin" ]; do
    sleep "$PAUSA"
    [ "$(docker inspect -f '{{.State.Health.Status}}' postiz 2>/dev/null)" = healthy ] || continue
    [ "$(docker exec postiz pm2 jlist 2>/dev/null | docker exec -i postiz node -e \
      'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const a=JSON.parse(s);console.log(a.length===3&&a.every(p=>p.pm2_env.status==="online")?"ok":"no")})' 2>/dev/null)" = ok ] || continue
    [ "$(docker exec postiz node -e 'require("http").get({host:"localhost",port:5000,path:"/",timeout:8000},r=>console.log(r.statusCode)).on("error",()=>console.log(0))' 2>/dev/null)" = 307 ] || continue
    # Se guarda antes de buscar: con pipefail, un `grep -q` que cierra la
    # tubería antes de tiempo convierte el acierto en fallo.
    pollers=$(docker exec temporal temporal task-queue describe --task-queue main --address temporal:7233 2>/dev/null) || continue
    grep -q "@$(docker inspect -f '{{.Config.Hostname}}' postiz) .*\(now\|second\)" <<<"$pollers" || continue
    log "sano (desde el arranque: $(( $(date +%s) - inicio )) s)"
    return 0
  done
  return 1
}

usar_imagen() {
  sed -i -E "s|^([[:space:]]*image: postiz-custom:)[^[:space:]]+|\1$1|" "$COMPOSE"
  docker compose -f "$COMPOSE" up -d --no-deps postiz
}

INICIO=$(date +%s)
usar_imagen "$NUEVA"
if ! sano_desde "$INICIO"; then
  log "no queda sano: vuelta a $ANTERIOR"
  usar_imagen "$ANTERIOR"
  if sano_desde "$(date +%s)"; then
    fallo "$NUEVA no quedó sano en $ESPERA_MAX s y se volvió a $ANTERIOR, que está sano.
Si el commit cambió el esquema, la base ya está migrada: volcado previo en $VOLCADO."
  fi
  fallo "$NUEVA no quedó sano y la vuelta a $ANTERIOR TAMPOCO. Postiz está caído.
Volcado previo: $VOLCADO."
fi

bash "$DIR/verifica-arranque.sh" || true

DIFIEREN=""
for f in build.sh verifica-arranque.sh desplegar.sh; do
  cmp -s "$DIR/$f" "$REPO/docs/architecture/scripts/$f" || DIFIEREN="$DIFIEREN $f"
done

SIN_AGENTE=1 "$ALERTAR" --stdin postiz-despliegue <<EOF
✅ Postiz desplegado: $OBJETIVO
$(git -C "$REPO" log -1 --format=%s "origin/$RAMA")
Antes corría $ANTERIOR.${DIFIEREN:+
Las copias vivas de$DIFIEREN en $DIR difieren de las del repo.}
EOF
rm -f "$FALLIDO"
log "desplegado $NUEVA"
