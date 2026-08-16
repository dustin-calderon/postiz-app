#!/bin/sh
# normalizar-video.sh — puerta de entrada de media de la ruta Notion → Postiz.
#
# Espejo del Paso 5 del skill clips (subir-media.sh): mide el video de origen
# y solo lo recodifica si esta fuera del techo publicable. El motivo es el
# mismo que alli: un master 4K a 38 Mbps (585 MB) no se publica — Meta no
# termina de procesarlo, el contenedor se queda IN_PROGRESS y el post muere.
# Paso el 2026-08-06 (dos Trial Reels) y el 2026-08-15 (trial wicked 1 2.mp4).
#
# Por aqui pasa TODO el media de la ruta Notion, no solo el video: el subflow
# manda un asset por invocacion sin saber que es. Recodificar es la excepcion
# —solo un video positivamente fuera de techo—; cualquier otra cosa sube tal
# cual, que es lo que hacia el pipeline entero antes del 2026-08-15.
#
# Uso: normalizar-video.sh <url-del-asset>
#   La URL tipica es la firmada de Notion (caduca ~1 h: medir y descargar
#   aqui, nunca arrastrarla entre pasadas).
#
# Salida: UNA linea JSON por stdout: {"id":..,"path":..,"normalizado":bool}
#   (el media ya subido a Postiz). Todo diagnostico va por stderr.
#   rc != 0 con el motivo en stderr si algo falla — el subflow de n8n escribe
#   ese motivo en el error_log de la fila de Notion.
#
# Las dos subidas van por 127.0.0.1:4007 (puerto local de la API de Postiz):
# sin Cloudflare de por medio no aplican ni el tope de ~100 MB por multipart
# ni el corte de respuestas a ~100 s del tunel.

ORG=30c506a6-0a2c-4661-95bb-abec2e14b3f2

# Techos de publicacion: 1080x1920 es lo que recomienda Instagram; el techo de
# bitrate no es el de Meta (25 Mbps) sino el que el uplink de casa sirve a
# tiempo. El objetivo de recodificacion son 8 Mbps: lo que produce una fuente
# 1080p normal, no una calidad inventada. (Identico a clips/subir-media.sh.)
MAX_ANCHO=1080
MAX_ALTO=1920
MAX_BPS=12000000

abort() { echo "ABORTADO: $1" >&2; exit 1; }

# La clave nunca se imprime ni viaja como argumento visible.
postiz_key() {
  k=$(docker exec postiz-postgres sh -c \
      "psql -U \$POSTGRES_USER -d \$POSTGRES_DB -t -A -c \"SELECT \\\"apiKey\\\" FROM \\\"Organization\\\" WHERE id='$ORG';\"" \
      2>/dev/null | tr -d '\r\n')
  [ -n "$k" ] || return 1
  printf '%s' "$k"
}

# Imprime "width=…", "height=…", "nb_frames=…", "duration=…" y "bit_rate=…",
# sea fichero o URL. Sobre una URL firmada ffprobe solo lee cabeceras (~2 s,
# sin descargar). El timeout no es decorativo: una lectura remota colgada
# colgaria la pasada entera del sync.
# `duration` se pide al CONTENEDOR y no al stream a proposito: el demuxer de
# imagen le inventa al stream una duracion de 0,04 s (un fotograma nominal).
medir() {
  timeout 60 ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height,nb_frames \
    -show_entries format=duration,bit_rate \
    -of default=noprint_wrappers=1 "$1" 2>/dev/null
}

campo() { printf '%s\n' "$1" | sed -n "s/^$2=//p" | head -1; }

# Cierto solo si el asset tiene una LINEA DE TIEMPO real: segundos de duracion
# o mas de un fotograma. Es lo unico que separa imagen de video en todos los
# formatos que entran por Notion. Lo verificado el 2026-08-16 sobre ffprobe:
#   - el contenedor no sirve: un HEIC de iPhone comparte contenedor con un MP4
#     ("mov,mp4,m4a,3gp,3g2,mj2"), asi que filtrar por formato o rompe las
#     fotos de iPhone o deja pasar videos, segun como se escriba;
#   - avg_frame_rate tampoco: ffmpeg reporta 25/1 hasta en un PNG;
#   - el codec tampoco: un HEIC es "hevc", igual que un video H.265;
#   - nb_frames es N/A (no 1) en PNG y JPEG, y la duracion del contenedor es
#     N/A en PNG/WebP pero 0,04 s en JPEG. Por eso hacen falta las dos.
# Residuo conocido y aceptado: un video cuyo contenedor no declare ni duracion
# ni numero de fotogramas (malformado) se clasifica como imagen y sube sin
# normalizar. Es mucho mas raro que una foto de iPhone en un carrusel y el
# dano es menor —lo rechaza Postiz al validar, no corrompe el post—, mientras
# que equivocarse al reves convierte cada foto en un MP4 de un fotograma.
es_video() {
  _d=${1%%.*}; _n=$2
  case "$_d" in ''|*[!0-9]*) _d=0 ;; esac
  case "$_n" in ''|*[!0-9]*) _n=0 ;; esac
  [ "$_d" -ge 1 ] || [ "$_n" -ge 2 ]
}

# Cumple solo si se conocen las tres medidas y ninguna pasa del techo.
# Una medida ausente NO cumple: se normaliza. Subir a ciegas algo que no se
# pudo medir es exactamente como se perdieron los Trial Reels del 2026-08-06;
# equivocarse hacia recodificar solo cuesta un par de minutos de CPU.
# Solo se aplica a lo que ya se sabe que es video: a una imagen no le aplica
# ningun techo de bitrate, y el suyo es N/A siempre.
es_publicable() {
  for v in "$1" "$2" "$3"; do
    case "$v" in ''|*[!0-9]*) return 1 ;; esac
  done
  [ "$1" -le "$MAX_ANCHO" ] && [ "$2" -le "$MAX_ALTO" ] && [ "$3" -le "$MAX_BPS" ]
}

main() {
  U=$1
  [ -n "$U" ] || abort 'falta la URL del asset'
  case "$U" in http://*|https://*) ;; *) abort 'la entrada debe ser una URL http(s)' ;; esac

  K=$(postiz_key) || abort 'apiKey de Postiz vacia'

  INFO=$(medir "$U")
  ANCHO=$(campo "$INFO" width); ALTO=$(campo "$INFO" height); BPS=$(campo "$INFO" bit_rate)
  DUR=$(campo "$INFO" duration); FRAMES=$(campo "$INFO" nb_frames)

  # Sin ni siquiera dimensiones no hay clasificacion posible y las dos salidas
  # son malas: subir a ciegas es el 2026-08-06, y recodificar a ciegas es
  # convertir una foto en un video. Se para y se dice por que.
  [ -n "$ANCHO" ] && [ -n "$ALTO" ] \
    || abort 'ffprobe no pudo leer el asset (ni dimensiones): ¿URL de Notion caducada o fichero corrupto?'

  if es_video "$DUR" "$FRAMES"; then TIPO=video; else TIPO=imagen; fi
  echo "MEDIDO=${ANCHO}x${ALTO} @ ${BPS:-N/A} bps · ${DUR:-N/A}s · ${FRAMES:-N/A} frames · TIPO=$TIPO" >&2

  # La recodificacion es la EXCEPCION: solo un video que se pasa del techo.
  if [ "$TIPO" = video ] && ! es_publicable "$ANCHO" "$ALTO" "$BPS"; then
    NORM=true
    echo 'NORMALIZANDO=1' >&2

    D=$(mktemp -d) || abort 'no se pudo crear el directorio temporal'
    # Se borra pase lo que pase: un 4K a medio bajar son cientos de MB, y
    # abort tambien dispara este trap porque hace exit.
    trap 'rm -rf "$D"' EXIT INT TERM
    ORIGEN="$D/origen"
    # Nombre fijo a proposito: acaba dentro del parseo de -F de curl (trata
    # ';' y ',' como separadores). Postiz deriva nombre y extension olfateando
    # los bytes, no del nombre que se le manda.
    PUB="$D/publicable.mp4"

    curl -fsS --max-time 900 -o "$ORIGEN" "$U" \
      || abort 'no se pudo descargar el video de origen (¿URL de Notion caducada?)'

    # fps de origen a proposito (forzarlo mete judder; Instagram acepta 23-60).
    # +faststart pone el indice al principio: Meta empieza a procesar sin
    # haberse bajado el fichero entero.
    # El timeout no es decorativo: esto corre bajo el cron de las 06:00 sin
    # nadie mirando, y un ffmpeg colgado colgaria la pasada entera del sync.
    # 30 min dan de sobra: el 4K de 585 MB/129 s se normalizo en ~3 min.
    timeout 1800 ffmpeg -v error -y -i "$ORIGEN" \
      -vf "scale=$MAX_ANCHO:$MAX_ALTO:force_original_aspect_ratio=decrease:force_divisible_by=2" \
      -c:v libx264 -profile:v high -preset veryfast \
      -b:v 8M -maxrate 10M -bufsize 16M -pix_fmt yuv420p \
      -c:a aac -b:a 128k -ar 48000 \
      -movflags +faststart "$PUB" \
      || abort 'ffmpeg no pudo normalizar el video'

    # El rc 0 de ffmpeg no demuestra que el resultado sirva: se vuelve a medir.
    INFO2=$(medir "$PUB")
    A2=$(campo "$INFO2" width); L2=$(campo "$INFO2" height); B2=$(campo "$INFO2" bit_rate)
    es_publicable "$A2" "$L2" "$B2" \
      || abort "el video normalizado sigue fuera de techo (${A2:-?}x${L2:-?} @ ${B2:-?} bps)"
    echo "NORMALIZADO=${A2}x${L2} @ ${B2} bps" >&2

    RESP=$(curl -s -X POST http://127.0.0.1:4007/api/public/v1/upload \
      -H "Authorization: $K" -F "file=@$PUB;type=video/mp4")
  else
    # Camino de siempre: Postiz se descarga el asset el mismo, en streaming.
    NORM=false
    RESP=$(jq -nc --arg u "$U" '{url:$u}' \
      | curl -s -X POST http://127.0.0.1:4007/api/public/v1/upload-from-url \
          -H "Authorization: $K" -H 'Content-Type: application/json' --data-binary @-)
  fi

  MID=$(printf '%s' "$RESP" | jq -r '.id // empty' 2>/dev/null)
  MP=$(printf '%s' "$RESP" | jq -r '.path // empty' 2>/dev/null)
  if [ -z "$MID" ] || [ -z "$MP" ]; then
    echo "Postiz no devolvio un media valido: $(printf '%s' "$RESP" | head -c 300)" >&2
    exit 1
  fi

  jq -nc --arg id "$MID" --arg path "$MP" --argjson n "$NORM" \
    '{id:$id,path:$path,normalizado:$n}'
}

main "$@"
