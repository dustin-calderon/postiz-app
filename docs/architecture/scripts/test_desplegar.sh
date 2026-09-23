#!/bin/bash
# Prueba desplegar.sh entero sin tocar nada real: un git de verdad en un
# directorio temporal y un `docker` de mentira que guarda en ficheros qué imagen
# corre y si está sana. Las copias de build.sh, alertar.sh y volcar-app.sh
# también son de mentira. Corre en Linux (el sed de desplegar.sh es el de GNU).
#
#   bash docs/architecture/scripts/test_desplegar.sh

set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/desplegar.sh"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
fallos=0

# ── el docker de mentira ──
mkdir -p "$T/bin" "$T/estado"
cat > "$T/bin/docker" <<'EOF'
#!/bin/bash
E="$ESTADO"
tag() { sed -n 's|^postiz-custom:||p' "$E/imagen"; }
case "$*" in
  "inspect -f {{.Config.Image}} postiz") cat "$E/imagen" ;;
  "inspect -f {{.Config.Hostname}} postiz") echo "c-$(tag)" ;;
  "inspect -f {{.State.Health.Status}} postiz")
    grep -qx "$(tag)" "$E/rotas" 2>/dev/null && echo unhealthy || echo healthy ;;
  "exec postiz pm2 jlist") echo '[]' ;;
  "exec -i postiz node -e "*) cat > /dev/null; echo ok ;;
  "exec postiz node -e "*) echo 307 ;;
  "exec temporal temporal task-queue describe "*)
    echo "  UNVERSIONED  workflow  1@c-$(tag)  now  100000" ;;
  "compose -f "*" up -d --no-deps postiz")
    sed -n 's|^[[:space:]]*image: ||p' "$3" > "$E/imagen"; echo "up $(cat "$E/imagen")" >> "$E/ups" ;;
  *) echo "docker de mentira: no sé hacer «$*»" >&2; exit 99 ;;
esac
EOF
chmod +x "$T/bin/docker"

# ── build.sh, verifica-arranque, alertar y volcar de mentira ──
mkdir -p "$T/postiz" "$T/ops/backup" "$T/volcados"
cat > "$T/postiz/build.sh" <<'EOF'
[ -e "$ESTADO/build-falla" ] && exit 1
sha=$(git -C "$DESPLEGAR_REPO" rev-parse --short HEAD)
sed -i -E "s|^([[:space:]]*image: postiz-custom:)[^[:space:]]+|\1local-$sha|" "$DESPLEGAR_DIR/docker-compose.yml"
EOF
echo 'echo verifica' > "$T/postiz/verifica-arranque.sh"
printf '#!/bin/bash\n[ "$1" = --stdin ] && shift\n{ echo "== $1 SIN_AGENTE=${SIN_AGENTE:-0}"; cat; } >> "$ESTADO/avisos"\n' > "$T/ops/alertar.sh"
printf '#!/bin/bash\necho volcado-de-$1\n' > "$T/ops/backup/volcar-app.sh"
chmod +x "$T/ops/alertar.sh" "$T/ops/backup/volcar-app.sh"

# ── el repo: un origen y el clon que despliega ──
git init -q --bare "$T/origen.git"
git clone -q "$T/origen.git" "$T/trabajo" 2>/dev/null
g() { git -C "$T/trabajo" -c user.email=t@t -c user.name=t "$@"; }
g checkout -q -b custom/postiz-dc
mkdir -p "$T/trabajo/apps" "$T/trabajo/docs"
commit() { echo "$RANDOM" > "$T/trabajo/$1"; g add -A; g commit -qm "$2"; g push -q origin custom/postiz-dc; g rev-parse --short HEAD; }
BASE=$(commit apps/a.ts "código base")
git clone -q -b custom/postiz-dc "$T/origen.git" "$T/repo"

export PATH="$T/bin:$PATH" ESTADO="$T/estado" DESPLEGAR_REPO="$T/repo" \
  DESPLEGAR_DIR="$T/postiz" DESPLEGAR_OPS="$T/ops" DESPLEGAR_VOLCADOS="$T/volcados" \
  DESPLEGAR_ESPERA_MAX=2 DESPLEGAR_PAUSA=0

corriendo() { echo "postiz-custom:local-$1" > "$T/estado/imagen"
  printf 'services:\n  postiz:\n    image: postiz-custom:local-%s\n' "$1" > "$T/postiz/docker-compose.yml"
  rm -f "$T/estado/avisos" "$T/estado/ups" "$T/estado/rotas" "$T/estado/build-falla"; }
es() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "MAL  $1: esperaba «$3», hay «$2»"; fallos=$((fallos+1)); fi; }
aviso() { cat "$T/estado/avisos" 2>/dev/null; }

echo "-- 1. Lo que corre es lo último: nada que hacer"
corriendo "$BASE"
bash "$SCRIPT" --si-hay-cambios
es "sin despliegue" "$(cat "$T/estado/ups" 2>/dev/null)" ""
es "sin aviso" "$(aviso)" ""

echo "-- 2. Solo cambió documentación: nada que hacer"
commit docs/x.md "docs" > /dev/null
bash "$SCRIPT" --si-hay-cambios
es "sin despliegue" "$(cat "$T/estado/ups" 2>/dev/null)" ""

echo "-- 3. Cambió código y queda sano: se despliega"
NUEVO=$(commit apps/b.ts "arreglo")
bash "$SCRIPT" --si-hay-cambios
es "corre la nueva" "$(cat "$T/estado/imagen")" "postiz-custom:local-$NUEVO"
es "avisa del éxito solo por Telegram" "$(aviso | head -2)" "== postiz-despliegue SIN_AGENTE=1
✅ Postiz desplegado: $NUEVO"
es "volcado antes" "$(cat "$T/volcados"/*.dump)" "volcado-de-postiz"
es "el clon avanzó" "$(git -C "$T/repo" rev-parse --short HEAD)" "$NUEVO"

echo "-- 4. La imagen nueva no queda sana: vuelve sola a la anterior"
corriendo "$BASE"; echo "local-$NUEVO" > "$T/estado/rotas"
bash "$SCRIPT" --si-hay-cambios; rc=$?
es "sale con error" "$rc" "1"
es "vuelve a correr la anterior" "$(cat "$T/estado/imagen")" "postiz-custom:local-$BASE"
es "compose en la anterior" "$(sed -n 's|^ *image: ||p' "$T/postiz/docker-compose.yml")" "postiz-custom:local-$BASE"
es "avisa al bus" "$(aviso | head -2)" "== postiz-despliegue SIN_AGENTE=0
🔴 Postiz: el despliegue de $NUEVO falló"
aviso | grep -q "se volvió a local-$BASE, que está sano" && echo "ok   dice que la vuelta atrás está sana" || { echo "MAL  no dice que la vuelta atrás está sana"; fallos=$((fallos+1)); }

echo "-- 5. Si ni la vuelta atrás queda sana, lo dice"
corriendo "$BASE"; printf 'local-%s\n' "$NUEVO" "$BASE" > "$T/estado/rotas"
bash "$SCRIPT" --si-hay-cambios
aviso | grep -q "TAMPOCO. Postiz está caído" && echo "ok   avisa de que Postiz está caído" || { echo "MAL  no avisa de la caída"; fallos=$((fallos+1)); }

echo "-- 6. El build falla: no se toca el contenedor"
corriendo "$BASE"; touch "$T/estado/build-falla"
bash "$SCRIPT" --si-hay-cambios; rc=$?
es "sale con error" "$rc" "1"
es "sin despliegue" "$(cat "$T/estado/ups" 2>/dev/null)" ""
aviso | grep -q "build.sh falló" && echo "ok   avisa del build" || { echo "MAL  no avisa del build"; fallos=$((fallos+1)); }

echo
[ "$fallos" -eq 0 ] && echo "TODO BIEN" || { echo "$fallos FALLOS"; exit 1; }
