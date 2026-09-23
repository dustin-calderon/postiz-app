#!/bin/bash
# Postiz Custom Build Script
# Construye la imagen desde /opt/repos/postiz-fork y deja el compose apuntando a ella.
# Uso: bash /opt/homeserver/postiz/build.sh
# Produce: postiz-custom:local-<short-sha>
#
# Una etiqueta por commit, y no una fija como postiz-custom:local, porque
# check-imagenes-publicas.py (Instalar-Home-Server) ata cada vulnerabilidad
# aceptada a la imagen que corre el contenedor. Con una etiqueta reutilizada, la
# aceptación sobreviviría al código que la justificaba; con el SHA, reconstruir
# desde otro commit hace que los hallazgos vuelvan a salir y se juzguen de nuevo.
#
# Copia versionada de /opt/homeserver/postiz/build.sh: si se toca una, se
# actualiza la otra (se comparan con md5sum).

set -euo pipefail

REPO_DIR="/opt/repos/postiz-fork"
COMPOSE="/opt/homeserver/postiz/docker-compose.yml"
IMAGE_NAME="postiz-custom"
SHORT_SHA=$(git -C "$REPO_DIR" rev-parse --short HEAD)
IMAGE_TAG="local-${SHORT_SHA}"
# La vuelta atrás es la imagen que CORRE, no la que dice el compose: si se
# construye dos veces sin `up -d` en medio, el compose ya apunta a la anterior.
ANTERIOR=$(docker inspect -f '{{.Config.Image}}' postiz 2>/dev/null | sed -nE "s|^${IMAGE_NAME}:||p")

echo "=== Postiz Custom Build ==="
echo "Branch : $(git -C "$REPO_DIR" branch --show-current)"
echo "Commit : ${SHORT_SHA}"
echo "Tag    : ${IMAGE_NAME}:${IMAGE_TAG} (el contenedor corre ahora ${IMAGE_NAME}:${ANTERIOR})"

docker build -f "${REPO_DIR}/Dockerfile.dev" -t "${IMAGE_NAME}:${IMAGE_TAG}" "${REPO_DIR}"

# El compose pasa a la imagen nueva. El contenedor en marcha no cambia hasta el
# `up -d`, igual que cuando construir movía postiz-custom:local.
sed -i -E "s|^([[:space:]]*image: ${IMAGE_NAME}:)[^[:space:]]+|\1${IMAGE_TAG}|" "$COMPOSE"

# Se borran SOLO los tags local-<sha> viejos, nunca la imagen nueva ni la que
# corría: esa es la vuelta atrás. No se usa docker image prune -f porque
# afectaría a todos los servicios de esta máquina, y se borra por tag, no por ID.
docker images "$IMAGE_NAME" --format "{{.Tag}}" | \
  grep -E '^local-' | \
  grep -v -x -e "$IMAGE_TAG" -e "$ANTERIOR" | \
  xargs -r -I{} docker rmi "${IMAGE_NAME}:{}" 2>/dev/null || true

echo "=== Build completado: ${IMAGE_NAME}:${IMAGE_TAG} ==="
echo ""
echo "SIGUIENTE PASO: para aplicar la nueva imagen al container en ejecucion, corre:"
echo "  docker compose -f ${COMPOSE} up -d postiz"
echo "Vuelta atras: poner 'image: ${IMAGE_NAME}:${ANTERIOR}' en ${COMPOSE} y repetir el up -d."
