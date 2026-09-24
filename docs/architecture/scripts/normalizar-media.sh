#!/bin/sh
# normalizar-media.sh — puerta de entrada de media de la ruta Notion → Postiz.
#
# Cada fichero de una fila pasa por aqui antes de subir a Postiz y sale en un
# formato que Instagram publica. La regla es la referencia de Meta (IG User
# Media: especificaciones de imagen, reels y stories) y sus errores 2207004,
# 2207005 y 2207026. Aqui se arregla lo que se arregla convirtiendo, sin
# decidir nada por la persona:
#   - foto que no es JPEG ni PNG (el HEIC del iPhone, WebP, GIF...) o que pasa
#     de 8 MiB: se convierte a JPEG;
#   - video que no es MOV/MP4, ni H.264/HEVC, ni de 23 a 60 fps, ni de audio
#     AAC hasta 48 kHz, o que pasa del techo de subida (abajo) o de 300 MB: se
#     recodifica a MP4 H.264.
# Lo que exige decidir (la duracion de un video, la proporcion de una foto)
# no se toca: lo rechaza Postiz al programar, con el motivo
# (instagram.media.rules.ts). Lo que ya cumple sube tal cual.
#
# PNG sube tal cual: la referencia pide JPEG, pero Instagram publica PNG con
# normalidad (son las laminas de todos los carruseles replicados).
#
# Uso: normalizar-media.sh <url-del-asset>
#   La URL tipica es la firmada de Notion (caduca ~1 h: medir y descargar
#   aqui, nunca arrastrarla entre pasadas).
#
# Salida: UNA linea JSON por stdout: {"id":..,"path":..,"normalizado":bool}
#   (el media ya subido a Postiz; normalizado = se convirtio aqui). Todo
#   diagnostico va por stderr. rc != 0 con el motivo en stderr si algo falla:
#   el subflow de n8n escribe ese motivo en el error_log de la fila de Notion.
#
# Las subidas van por 127.0.0.1:4007 (puerto local de la API de Postiz): sin
# Cloudflare de por medio no aplican ni el tope de ~100 MB por multipart ni el
# corte de respuestas a ~100 s del tunel.
#
# Necesita ffmpeg/ffprobe, jq, curl y heif-convert (paquete libheif-examples):
# el ffmpeg de Ubuntu 24.04 no abre un HEIC de iPhone.
#
# Copia viva: /opt/homeserver/postiz/normalizar-media.sh.

ORG=30c506a6-0a2c-4661-95bb-abec2e14b3f2

# Techo de subida del video: 1080x1920 es lo que recomienda Instagram; el
# techo de bitrate no es el de Meta (25 Mbps) sino el que el uplink de casa
# sirve a tiempo. El objetivo de recodificacion son 8 Mbps: lo que produce
# una fuente 1080p normal, no una calidad inventada. (Identico al skill clips,
# subir-media.sh.)
MAX_ANCHO=1080
MAX_ALTO=1920
MAX_BPS=12000000
OBJETIVO_BPS=8000000
AUDIO_BPS=128000
# Topes de Meta. Una story de video no puede pasar de 100 MB, pero con el
# techo de 12 Mbps y su maximo de 60 s (que valida Postiz) no llega a 91 MB.
MAX_BYTES_VIDEO=300000000
MAX_BYTES_FOTO=8388608
# Meta reduce a 1440 px de ancho cualquier foto mas ancha: convertir a ese
# ancho no quita nada de lo que se ve y deja el JPEG muy por debajo de 8 MiB.
MAX_ANCHO_FOTO=1440

abort() { echo "ABORTADO: $1" >&2; exit 1; }

# La clave nunca se imprime ni viaja como argumento visible.
postiz_key() {
  k=$(docker exec postiz-postgres sh -c \
      "psql -U \$POSTGRES_USER -d \$POSTGRES_DB -t -A -c \"SELECT \\\"apiKey\\\" FROM \\\"Organization\\\" WHERE id='$ORG';\"" \
      2>/dev/null | tr -d '\r\n')
  [ -n "$k" ] || return 1
  printf '%s' "$k"
}

# Mide un fichero o una URL y deja en variables lo que decide que hacer con
# el. Sobre una URL firmada ffprobe solo lee cabeceras (~2 s, sin descargar).
# El timeout no es decorativo: una lectura remota colgada colgaria la pasada
# entera del sync. `duration` se pide al CONTENEDOR y no al stream a
# proposito: el demuxer de imagen le inventa al stream 0,04 s.
medir() {
  J=$(timeout 60 ffprobe -v error -print_format json -show_format -show_streams "$1" 2>/dev/null) || J='{}'
  v() { printf '%s' "$J" | jq -r "$1 // empty" 2>/dev/null; }
  ANCHO=$(v '[.streams[]? | select(.codec_type=="video")][0].width')
  ALTO=$(v '[.streams[]? | select(.codec_type=="video")][0].height')
  CODEC=$(v '[.streams[]? | select(.codec_type=="video")][0].codec_name')
  FRAMES=$(v '[.streams[]? | select(.codec_type=="video")][0].nb_frames')
  FPS=$(v '[.streams[]? | select(.codec_type=="video")][0].avg_frame_rate')
  AUDIO=$(v '[.streams[]? | select(.codec_type=="audio")][0].codec_name')
  HZ=$(v '[.streams[]? | select(.codec_type=="audio")][0].sample_rate')
  CONTENEDOR=$(v '.format.format_name')
  DUR=$(v '.format.duration')
  BPS=$(v '.format.bit_rate')
  BYTES=$(v '.format.size')
}

entero() { case "$1" in ''|*[!0-9]*) echo 0 ;; *) echo "$1" ;; esac; }

# Cierto solo si el asset tiene una LINEA DE TIEMPO real: segundos de duracion
# o mas de un fotograma. Es lo unico que separa imagen de video en todos los
# formatos que entran por Notion:
#   - el contenedor no sirve: MOV y MP4 comparten demuxer con otros formatos;
#   - avg_frame_rate tampoco: ffmpeg reporta 25/1 hasta en un PNG;
#   - nb_frames es N/A (no 1) en PNG y JPEG, y la duracion del contenedor es
#     N/A en PNG/WebP pero 0,04 s en JPEG. Por eso hacen falta las dos.
# Residuo conocido y aceptado: un video cuyo contenedor no declare ni duracion
# ni numero de fotogramas (malformado) se clasifica como imagen y se convierte
# a JPEG de su primer fotograma. Es mucho mas raro que una foto en un carrusel,
# y equivocarse al reves convierte cada foto en un MP4 de un fotograma.
es_video() {
  [ "$(entero "${DUR%%.*}")" -ge 1 ] || [ "$(entero "$FRAMES")" -ge 2 ]
}

# Por que hay que recodificar un video, o nada si ya lo publica Instagram tal
# cual. Una medida ausente cuenta como fuera: subir a ciegas algo que no se
# pudo medir es como se perdieron los Trial Reels del 2026-08-06, y
# equivocarse hacia recodificar solo cuesta minutos de CPU.
motivo_video() {
  case "$CONTENEDOR" in *mov*) ;; *) echo "contenedor $CONTENEDOR"; return ;; esac
  case "$CODEC" in h264|hevc) ;; *) echo "codec $CODEC"; return ;; esac
  n=$(entero "${FPS%%/*}"); d=$(entero "${FPS##*/}")
  { [ "$d" -gt 0 ] && [ $((n)) -ge $((23 * d)) ] && [ $((n)) -le $((60 * d)) ]; } \
    || { echo "fps $FPS"; return; }
  if [ -n "$AUDIO" ]; then
    [ "$AUDIO" = aac ] && [ "$(entero "$HZ")" -le 48000 ] \
      || { echo "audio $AUDIO ${HZ:-?} Hz"; return; }
  fi
  a=$(entero "$ANCHO"); l=$(entero "$ALTO"); b=$(entero "$BPS")
  { [ "$a" -gt 0 ] && [ "$l" -gt 0 ] && [ "$b" -gt 0 ] && [ "$a" -le "$MAX_ANCHO" ] \
    && [ "$l" -le "$MAX_ALTO" ] && [ "$b" -le "$MAX_BPS" ]; } \
    || { echo "fuera del techo ${ANCHO:-?}x${ALTO:-?} @ ${BPS:-?} bps"; return; }
  [ "$(entero "$BYTES")" -gt 0 ] && [ "$(entero "$BYTES")" -le "$MAX_BYTES_VIDEO" ] \
    || { echo "tamano ${BYTES:-?} bytes"; return; }
}

# El bitrate de video que deja el fichero dentro de 300 MB, sin pasar de 8 Mbps.
# Con un 5 % de margen para el contenedor y los picos del VBR.
bitrate_objetivo() {
  s=$(entero "${DUR%%.*}")
  if [ "$s" -le 0 ]; then echo "$OBJETIVO_BPS"; return; fi
  cabe=$(( MAX_BYTES_VIDEO / 100 * 95 * 8 / (s + 1) - AUDIO_BPS ))
  [ "$cabe" -lt "$OBJETIVO_BPS" ] && echo "$cabe" || echo "$OBJETIVO_BPS"
}

subir_fichero() { # <fichero> <tipo mime>
  curl -s -X POST http://127.0.0.1:4007/api/public/v1/upload \
    -H "Authorization: $K" -F "file=@$1;type=$2"
}

# Una foto a JPEG sRGB de como mucho 1440 px de ancho. La transparencia se
# aplana sobre blanco: JPEG no la tiene, y sin aplanar lo transparente saldria
# del color que guarde el pixel, casi siempre negro.
a_jpeg() { # <entrada> <salida>
  timeout 300 ffmpeg -v error -y -i "$1" -frames:v 1 -filter_complex \
    "[0:v]scale='min($MAX_ANCHO_FOTO,iw)':-2,format=rgba,split[fondo][foto];[fondo]drawbox=c=white:t=fill[blanco];[blanco][foto]overlay,format=yuvj420p" \
    -q:v 2 "$2" || return 1
  [ "$(stat -c %s "$2")" -le "$MAX_BYTES_FOTO" ]
}

main() {
  U=$1
  [ -n "$U" ] || abort 'falta la URL del asset'
  case "$U" in http://*|https://*) ;; *) abort 'la entrada debe ser una URL http(s)' ;; esac

  K=$(postiz_key) || abort 'apiKey de Postiz vacia'

  D=$(mktemp -d) || abort 'no se pudo crear el directorio temporal'
  # Se borra pase lo que pase: un 4K a medio bajar son cientos de MB, y abort
  # tambien dispara este trap porque hace exit.
  trap 'rm -rf "$D"' EXIT INT TERM
  ORIGEN="$D/origen"
  bajar() {
    curl -fsS --max-time 900 -o "$ORIGEN" "$U" \
      || abort 'no se pudo descargar el fichero de origen (¿URL de Notion caducada?)'
  }

  medir "$U"
  NORM=false
  RESP=''

  if [ -z "$ANCHO" ] || [ -z "$ALTO" ]; then
    # ffprobe no lo abre. Puede ser un HEIF (el HEIC del iPhone), que el
    # ffmpeg de Ubuntu no lee: se prueba con heif-convert antes de rendirse.
    bajar
    heif-convert "$ORIGEN" "$D/heif.png" >/dev/null 2>&1 \
      || abort 'no se pudo leer el fichero: ni ffprobe ni heif-convert lo reconocen como foto o video (¿URL de Notion caducada o fichero corrupto?)'
    a_jpeg "$D/heif.png" "$D/foto.jpg" || abort 'no se pudo convertir el HEIC a JPEG'
    echo 'CONVERTIDO=heif a jpeg' >&2
    NORM=true
    RESP=$(subir_fichero "$D/foto.jpg" image/jpeg)

  elif es_video; then
    MOTIVO=$(motivo_video)
    echo "MEDIDO=${ANCHO}x${ALTO} ${CODEC} ${FPS} fps en ${CONTENEDOR} · audio ${AUDIO:-no} ${HZ} · ${BPS:-N/A} bps · ${DUR:-N/A} s · ${BYTES:-N/A} bytes" >&2
    if [ -n "$MOTIVO" ]; then
      echo "RECODIFICANDO=$MOTIVO" >&2
      NORM=true
      bajar
      # Nombre fijo a proposito: acaba dentro del parseo de -F de curl (trata
      # ';' y ',' como separadores). Postiz deriva nombre y extension
      # olfateando los bytes, no del nombre que se le manda.
      PUB="$D/publicable.mp4"
      VB=$(bitrate_objetivo)
      # Los fps se tocan solo si estan fuera de 23-60: forzarlos dentro del
      # rango mete judder. +faststart pone el indice al principio: Meta empieza
      # a procesar sin haberse bajado el fichero entero. La escala solo reduce.
      n=$(entero "${FPS%%/*}"); d=$(entero "${FPS##*/}")
      FILTRO="scale='min($MAX_ANCHO,iw)':'min($MAX_ALTO,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
      if [ "$d" -eq 0 ] || [ $((n)) -gt $((60 * d)) ]; then FILTRO="$FILTRO,fps=60"
      elif [ $((n)) -lt $((23 * d)) ]; then FILTRO="$FILTRO,fps=30"; fi
      # El timeout no es decorativo: esto corre bajo el cron de las 06:00 sin
      # nadie mirando, y un ffmpeg colgado colgaria la pasada entera del sync.
      timeout 1800 ffmpeg -v error -y -i "$ORIGEN" -vf "$FILTRO" \
        -c:v libx264 -profile:v high -preset veryfast \
        -b:v "$VB" -maxrate $((VB * 5 / 4)) -bufsize $((VB * 2)) -pix_fmt yuv420p \
        -c:a aac -b:a "$AUDIO_BPS" -ar 48000 \
        -movflags +faststart "$PUB" \
        || abort 'ffmpeg no pudo recodificar el video'
      # El rc 0 de ffmpeg no demuestra que el resultado sirva: se vuelve a medir.
      medir "$PUB"
      RESTO=$(motivo_video)
      [ -z "$RESTO" ] || abort "el video recodificado sigue sin servir: $RESTO"
      echo "RECODIFICADO=${ANCHO}x${ALTO} @ ${BPS} bps · ${BYTES} bytes" >&2
      RESP=$(subir_fichero "$PUB" video/mp4)
    fi

  else
    echo "MEDIDO=foto ${ANCHO}x${ALTO} ${CODEC} · ${BYTES:-N/A} bytes" >&2
    if ! { { [ "$CODEC" = mjpeg ] || [ "$CODEC" = png ]; } \
           && [ "$(entero "$BYTES")" -gt 0 ] && [ "$(entero "$BYTES")" -le "$MAX_BYTES_FOTO" ]; }; then
      bajar
      a_jpeg "$ORIGEN" "$D/foto.jpg" || abort "no se pudo convertir la foto ($CODEC) a JPEG de menos de 8 MiB"
      echo "CONVERTIDO=$CODEC a jpeg" >&2
      NORM=true
      RESP=$(subir_fichero "$D/foto.jpg" image/jpeg)
    fi
  fi

  if [ -z "$RESP" ]; then
    # Ya cumple: Postiz se descarga el asset el mismo, en streaming.
    RESP=$(jq -nc --arg u "$U" '{url:$u}' \
      | curl -s -X POST http://127.0.0.1:4007/api/public/v1/upload-from-url \
          -H "Authorization: $K" -H 'Content-Type: application/json' --data-binary @-)
  fi

  MID=$(printf '%s' "$RESP" | jq -r '.id // empty' 2>/dev/null)
  MP=$(printf '%s' "$RESP" | jq -r '.path // empty' 2>/dev/null)
  if [ -z "$MID" ] || [ -z "$MP" ]; then
    # Postiz contesta {msg} o {message} (a veces una lista); lo que va al
    # error_log de la fila es ese texto, no el JSON entero.
    MOTIVO=$(printf '%s' "$RESP" | jq -r '(.msg // .message // empty)
      | if type == "array" then join("; ") else tostring end' 2>/dev/null)
    echo "Postiz no devolvio un media valido: ${MOTIVO:-$(printf '%s' "$RESP" | head -c 300)}" >&2
    exit 1
  fi

  jq -nc --arg id "$MID" --arg path "$MP" --argjson n "$NORM" \
    '{id:$id,path:$path,normalizado:$n}'
}

main "$@"
