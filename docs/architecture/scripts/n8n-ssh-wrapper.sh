#!/bin/sh
# n8n-ssh-wrapper.sh — comando forzado (authorized_keys) de la clave SSH de n8n.
#
# La clave de n8n solo puede ejecutar dos cosas: normalizar-video.sh con una URL
# como unico argumento, y replicar.sh (replica de carruseles) sin argumentos. n8n esta expuesto a internet: si sus credenciales caen, esta
# clave no puede convertirse en una shell en el host.
#
# El cliente NO ejecuta nada directamente: su comando llega entero en
# SSH_ORIGINAL_COMMAND y aqui se valida antes de exec (sin pasar por sh -c,
# que reinterpretaria metacaracteres).
#
# El nodo SSH de n8n debe mandar la URL SIN comillas (no lleva espacios).

SCRIPT=/opt/homeserver/postiz/normalizar-video.sh
REPLICAR=/opt/apps/carrusel-ig/replicar.sh

deny() {
  echo "clave restringida: solo '$SCRIPT <url>' o '$REPLICAR' (recibido: $SSH_ORIGINAL_COMMAND)" >&2
  exit 127
}

# Divide por espacios (una URL firmada no los tiene; '&' y '?' no separan).
# shellcheck disable=SC2086
set -- $SSH_ORIGINAL_COMMAND

# El nodo SSH de n8n antepone `cd <dir> ; ` por su parametro cwd (verificado
# en la traza del 2026-08-15; con otras versiones podria ser `&&`). El prefijo
# es inocuo —el script no depende del directorio— y se descarta.
if [ "$#" -ge 3 ] && [ "$1" = "cd" ] && { [ "$3" = ";" ] || [ "$3" = "&&" ]; }; then
  shift 3
fi

# replicar.sh vuelve al instante y sigue en segundo plano: no admite argumentos.
if [ "$#" -eq 1 ] && [ "$1" = "$REPLICAR" ]; then
  exec "$REPLICAR"
fi

[ "$#" -eq 2 ] || deny
[ "$1" = "$SCRIPT" ] || deny
case "$2" in
  http://*|https://*) ;;
  *) deny ;;
esac
# Lista blanca de caracteres de URL: nada de comillas, ';', '`', '$', '(' ...
case "$2" in
  *[!A-Za-z0-9:/?=\&%._~+-]*) deny ;;
esac

exec "$SCRIPT" "$2"
