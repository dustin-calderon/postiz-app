#!/bin/sh
# n8n-ssh-wrapper.sh — comando forzado (authorized_keys) de la clave SSH de n8n.
#
# La clave de n8n solo puede ejecutar tres cosas: normalizar-video.sh con una
# URL como unico argumento, replicar.sh (replica de carruseles) sin argumentos,
# y avisar al bus de incidencias (alertar.sh) con origen n8n o kuma-<monitor>.
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
ALERTAR=/opt/repos/instalar-home-server/server/ops/alertar.sh

deny() {
  echo "clave restringida: solo '$SCRIPT <url>', '$REPLICAR' o '$ALERTAR alertar|encolar <origen> <mensaje en base64>' (recibido: $SSH_ORIGINAL_COMMAND)" >&2
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

# El bus de incidencias. Los fallos de los workflows de n8n (su Error Trigger)
# van con origen `n8n`, y las caidas que avisa Uptime Kuma, con `kuma-<monitor>`.
# Ningun otro origen: hay origenes con runbook que actuan solos (actualizar una
# app, por ejemplo), y una credencial de n8n robada no debe poder dispararlos.
# El mensaje va en base64 porque lleva espacios y comillas, y el nodo SSH de n8n
# no puede mandarlo por la entrada estandar.
if [ "$#" -eq 4 ] && [ "$1" = "$ALERTAR" ]; then
  case "$2" in alertar|encolar) ;; *) deny ;; esac
  case "$3" in n8n|kuma-*) ;; *) deny ;; esac
  case "$3" in *[!a-z0-9-]*) deny ;; esac
  case "$4" in *[!A-Za-z0-9+/=]*) deny ;; esac
  mensaje=$(printf '%s' "$4" | base64 -d 2>/dev/null) || deny
  # Sin esto, la incidencia diria que la lanzo una sesion SSH, y el triage trata
  # lo que sale de una sesion SSH como sospechoso de prueba a mano.
  export ALERTAR_QUIEN="n8n · workflow «Bus de incidencias» por su clave SSH restringida"
  [ "$2" = encolar ] && exec "$ALERTAR" encolar "$3" "$mensaje"
  exec "$ALERTAR" "$3" "$mensaje"
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
