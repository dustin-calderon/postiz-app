#!/bin/bash
# test_normalizar-media.sh — prueba normalizar-media.sh de verdad, en el Beelink.
#
# Genera ficheros que Instagram no publica tal cual, los sirve en local, los
# pasa por el script y comprueba que lo que llega a Postiz si lo publica
# Instagram (referencia de Meta, IG User Media). Borra de Postiz lo que sube.
#
#   test_normalizar-media.sh [script]    por defecto, la copia viva
#
# Lo que ya cumple no se prueba aqui: sube por upload-from-url, que no acepta
# URLs locales (la guarda SSRF de Postiz). Ese camino lo cubre la bateria del
# pipeline (suite-pruebas-postiz.py) con ficheros de Notion.
#
# Borrar un media en Postiz solo lo marca: el fichero lo quita la Phase 2 a los
# 7 dias, y hasta entonces el espejo nocturno lo copiaria a Drive, que no borra
# nunca. Por eso la prueba borra los suyos del disco en el acto (sudo: los
# escribe el contenedor como root). Son ~250 MB por pasada.
#
# El HEIC de prueba (fixtures/teselas.heic) lo hizo macOS, como el de un
# iPhone: una rejilla de teselas HEVC. Aqui no se puede generar: el heif-enc
# de Ubuntu no trae codificador HEVC.

set -uo pipefail

SCRIPT=${1:-/opt/homeserver/postiz/normalizar-media.sh}
AQUI=$(cd "$(dirname "$0")" && pwd)
ORG=30c506a6-0a2c-4661-95bb-abec2e14b3f2
DISCO=/mnt/seagate/postiz-media
T=$(mktemp -d)
FALLOS=0
SUBIDOS=()
FICHEROS=()

K=$(docker exec postiz-postgres sh -c \
    "psql -U \$POSTGRES_USER -d \$POSTGRES_DB -t -A -c \"SELECT \\\"apiKey\\\" FROM \\\"Organization\\\" WHERE id='$ORG';\"" \
    2>/dev/null | tr -d '\r\n')
[ -n "$K" ] || { echo "sin apiKey de Postiz"; exit 2; }

PUERTO=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
python3 -m http.server "$PUERTO" --bind 127.0.0.1 --directory "$T" >/dev/null 2>&1 &
SERVIDOR=$!

limpiar() {
  for id in "${SUBIDOS[@]}"; do
    curl -s -o /dev/null -X DELETE "http://127.0.0.1:4007/api/public/v1/media/$id" -H "Authorization: $K"
  done
  for f in "${FICHEROS[@]}"; do
    case "$f" in "$DISCO"/*) sudo -n rm -f "$f" ;; esac
  done
  kill "$SERVIDOR" 2>/dev/null
  rm -rf "$T"
}
trap limpiar EXIT

mal() { echo "  FALLA: $1"; FALLOS=$((FALLOS + 1)); }

# Pasa un fichero por el script. Deja en SALIDA el fichero subido a Postiz.
convertir() { # <nombre>
  local r id path
  SALIDA=''
  r=$("$SCRIPT" "http://127.0.0.1:$PUERTO/$1" 2>"$T/$1.err") || { mal "rc != 0: $(tail -1 "$T/$1.err")"; return 1; }
  id=$(jq -r .id <<<"$r"); path=$(jq -r .path <<<"$r")
  SUBIDOS+=("$id")
  [ "$(jq -r .normalizado <<<"$r")" = true ] || mal 'normalizado no es true'
  SALIDA="$DISCO/${path#*/uploads/}"
  FICHEROS+=("$SALIDA")
  [ -f "$SALIDA" ] || { mal "no esta en disco: $SALIDA"; return 1; }
}

sonda() { # <fichero> <expresion jq sobre el JSON de ffprobe>
  ffprobe -v error -print_format json -show_format -show_streams "$1" | jq -r "$2"
}

es() { # <descripcion> <valor> <esperado>
  [ "$2" = "$3" ] && echo "  ok: $1 = $2" || mal "$1 = $2 (se esperaba $3)"
}

v='[.streams[] | select(.codec_type=="video")][0]'
a='[.streams[] | select(.codec_type=="audio")][0]'

echo "== foto HEIC del iPhone (teselas) -> JPEG"
cp "$AQUI/fixtures/teselas.heic" "$T/teselas.heic"
if convertir teselas.heic; then
  es codec "$(sonda "$SALIDA" "$v.codec_name")" mjpeg
  es tamano "$(sonda "$SALIDA" "\"\($v.width)x\($v.height)\"")" 1280x960
fi

echo "== foto WebP -> JPEG"
ffmpeg -v error -f lavfi -i testsrc2=s=800x1000 -frames:v 1 "$T/foto.webp"
convertir foto.webp && es codec "$(sonda "$SALIDA" "$v.codec_name")" mjpeg

echo "== foto GIF -> JPEG"
ffmpeg -v error -f lavfi -i testsrc2=s=800x1000 -frames:v 1 "$T/foto.gif"
convertir foto.gif && es codec "$(sonda "$SALIDA" "$v.codec_name")" mjpeg

echo "== foto AVIF -> JPEG"
ffmpeg -v error -f lavfi -i testsrc2=s=800x1000 -frames:v 1 -c:v libaom-av1 "$T/foto.avif"
convertir foto.avif && es codec "$(sonda "$SALIDA" "$v.codec_name")" mjpeg

echo "== PNG de mas de 8 MiB con transparencia -> JPEG de 1440 px, fondo blanco"
ffmpeg -v error -f lavfi -i "nullsrc=s=3000x3000,format=rgba,geq=r='random(1)*255':g='random(2)*255':b='random(3)*255':a='if(lt(X,1500),0,255)'" \
  -frames:v 1 "$T/grande.png"
echo "  origen: $(stat -c %s "$T/grande.png") bytes, $(sonda "$T/grande.png" "$v.pix_fmt")"
if convertir grande.png; then
  es codec "$(sonda "$SALIDA" "$v.codec_name")" mjpeg
  es ancho "$(sonda "$SALIDA" "$v.width")" 1440
  [ "$(stat -c %s "$SALIDA")" -le 8388608 ] && echo "  ok: <= 8 MiB" || mal "pasa de 8 MiB"
  es 'pixel transparente' "$(ffmpeg -v error -i "$SALIDA" -vf 'crop=8:8:100:700,scale=1:1,format=rgb24' -f rawvideo - | od -An -tu1 | tr -s ' ')" ' 255 255 255'
fi

echo "== video WebM VP9 -> MP4 H.264"
ffmpeg -v error -f lavfi -i testsrc2=s=720x1280:r=30 -t 4 -c:v libvpx-vp9 -b:v 1M "$T/clip.webm"
if convertir clip.webm; then
  es codec "$(sonda "$SALIDA" "$v.codec_name")" h264
  es contenedor "$(sonda "$SALIDA" .format.format_name)" 'mov,mp4,m4a,3gp,3g2,mj2'
  es 'no amplia' "$(sonda "$SALIDA" "\"\($v.width)x\($v.height)\"")" 720x1280
fi

echo "== video a 120 fps -> 60 fps"
ffmpeg -v error -f lavfi -i testsrc2=s=720x1280:r=120 -t 4 -c:v libx264 -pix_fmt yuv420p "$T/rapido.mp4"
convertir rapido.mp4 && es fps "$(sonda "$SALIDA" "$v.avg_frame_rate")" 60/1

echo "== audio PCM a 96 kHz -> AAC a 48 kHz"
ffmpeg -v error -f lavfi -i testsrc2=s=720x1280:r=30 -f lavfi -i sine=r=96000 -t 4 \
  -c:v libx264 -pix_fmt yuv420p -c:a pcm_s24le "$T/pcm.mov"
if convertir pcm.mov; then
  es audio "$(sonda "$SALIDA" "$a.codec_name")" aac
  es hz "$(sonda "$SALIDA" "$a.sample_rate")" 48000
fi

echo "== video dentro del techo pero de mas de 300 MB -> por debajo de 300 MB"
ffmpeg -v error -f lavfi -i "nullsrc=s=320x240:r=30,geq=random(1)*255:128:128" -t 230 \
  -c:v libx264 -preset ultrafast -b:v 11M -maxrate 11M -bufsize 22M -pix_fmt yuv420p "$T/largo.mp4"
echo "  origen: $(stat -c %s "$T/largo.mp4") bytes"
if convertir largo.mp4; then
  [ "$(stat -c %s "$SALIDA")" -le 300000000 ] && echo "  ok: $(stat -c %s "$SALIDA") bytes <= 300 MB" || mal "pasa de 300 MB"
fi

echo "== fichero ilegible -> rc != 0 con motivo"
head -c 20000 /dev/urandom > "$T/basura.bin"
if "$SCRIPT" "http://127.0.0.1:$PUERTO/basura.bin" >/dev/null 2>"$T/basura.err"; then
  mal 'rc 0 con un fichero ilegible'
else
  echo "  ok: $(tail -1 "$T/basura.err")"
fi

echo
[ "$FALLOS" -eq 0 ] && echo "TODO BIEN" || { echo "$FALLOS FALLOS"; exit 1; }
