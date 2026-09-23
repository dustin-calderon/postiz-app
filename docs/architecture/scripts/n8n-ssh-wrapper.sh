#!/bin/sh
# n8n-ssh-wrapper.sh — comando forzado (authorized_keys) de la clave SSH de n8n.
#
# La clave de n8n solo puede ejecutar cuatro cosas: normalizar-video.sh con una
# URL como unico argumento, replicar.sh (replica de carruseles) sin argumentos,
# turno-sync.sh con un id de ejecucion (el turno del sync, solo lectura), y
# encolar en el bus de incidencias (alertar.sh) con origen n8n-<workflow>,
# kuma-<monitor> o autoheal-<contenedor>.
# n8n esta expuesto a internet: si sus credenciales caen, esta clave no puede
# convertirse en una shell en el host.
#
# El cliente NO ejecuta nada directamente: su comando llega entero en
# SSH_ORIGINAL_COMMAND y aqui se valida antes de exec (sin pasar por sh -c,
# que reinterpretaria metacaracteres).
#
# El nodo SSH de n8n debe mandar la URL SIN comillas (no lleva espacios).

SCRIPT=/opt/homeserver/postiz/normalizar-video.sh
REPLICAR=/opt/apps/carrusel-ig/replicar.sh
TURNO=/opt/homeserver/postiz/turno-sync.sh
ALERTAR=/opt/repos/instalar-home-server/server/ops/alertar.sh

deny() {
  echo "clave restringida: solo '$SCRIPT <url>', '$REPLICAR', '$TURNO <id>' o '$ALERTAR encolar <origen> <mensaje en base64>' (recibido: $SSH_ORIGINAL_COMMAND)" >&2
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

# El turno del sync: solo lee, y su unico argumento es un id de ejecucion.
if [ "$#" -eq 2 ] && [ "$1" = "$TURNO" ]; then
  case "$2" in ''|*[!0-9]*) deny ;; esac
  exec "$TURNO" "$2"
fi

# El bus de incidencias: solo encolar, que no avisa a nadie (lo decide el
# triage). Los fallos de los workflows de n8n (su Error Trigger) van con origen
# `n8n-<workflow>`, las caidas que ve Uptime Kuma con `kuma-<monitor>` y los
# reinicios de autoheal con `autoheal-<contenedor>`: un origen por cosa, porque
# el bus identifica una incidencia por su origen. Ningun otro: hay origenes con
# runbook que actuan solos (actualizar una app, por ejemplo), y una credencial
# de n8n robada no debe poder dispararlos.
# El mensaje va en base64 porque lleva espacios y comillas, y el nodo SSH de n8n
# no puede mandarlo por la entrada estandar.
if [ "$#" -eq 4 ] && [ "$1" = "$ALERTAR" ]; then
  [ "$2" = encolar ] || deny
  case "$3" in n8n-?*|kuma-?*|autoheal-?*) ;; *) deny ;; esac
  case "$3" in *[!a-z0-9-]*) deny ;; esac
  case "$4" in *[!A-Za-z0-9+/=]*) deny ;; esac
  mensaje=$(printf '%s' "$4" | base64 -d 2>/dev/null) || deny
  # Sin esto, la incidencia diria que la lanzo una sesion SSH, y el triage trata
  # lo que sale de una sesion SSH como sospechoso de prueba a mano.
  export ALERTAR_QUIEN="n8n · workflow «Bus de incidencias» por su clave SSH restringida"
  exec "$ALERTAR" encolar "$3" "$mensaje"
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
