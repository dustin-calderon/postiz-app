# -*- coding: utf-8 -*-
"""Base del archivador de Drive: constantes, log, latido y accesos a Postiz, Notion y rclone."""
import json, os, re, subprocess, sys, unicodedata
import urllib.parse, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

PUBLICADO_ID = "1RkW1J4lc2X-qmOTqrRsJwQc1uuDMMN6G"
REMOTO = "gdrive-work"
RAIZ_DISCO = "/mnt/seagate/postiz-media"
DS_NOTION = "186a2405-a123-81dc-832f-000b82a65c0c"  # fuente de datos del calendario (API 2025-09-03)
REGISTRO_WEB = "/opt/homeserver/scripts/.postiz-archivo-web.json"
LOG = "/var/log/postiz-archivo.log"
# publishDate se guarda en UTC. La zona se resuelve con la base de datos del
# sistema, NO con un desfase fijo: +2 solo vale en verano, y una carpeta
# fechada mal en noviembre es un error que no se detecta hasta que molesta.
MADRID = ZoneInfo("Europe/Madrid")
SECO = "--seco" in sys.argv

TOK = os.environ["NOTION_API_KEY"]
NH = {"Authorization": "Bearer " + TOK, "Notion-Version": "2025-09-03",
      "Content-Type": "application/json"}


def log(msg):
    linea = "[%s] archivo: %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(linea)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except IOError:
        pass


def latido(ok, mensaje=""):
    """Avisa a un monitor externo de como termino la pasada.

    Inerte mientras POSTIZ_ARCHIVO_PING_URL no exista: sin esa variable no hace
    absolutamente nada, asi que añadirlo no cambia el comportamiento de hoy.
    La URL la da un monitor de tipo Push de Uptime Kuma, que ya corre en este
    servidor y es quien decide a quien avisar.

    Se eligio Push y no un chequeo activo por una razon concreta: un monitor
    Push se cae solo cuando DEJA de recibir el latido, asi que cubre tambien el
    caso de que el cron no llegue a ejecutarse. Era el hueco real -- el script
    ya salia con codigo distinto de cero cuando fallaba, pero el cron manda la
    salida a /dev/null y nadie la miraba.
    """
    destino = os.environ.get("POSTIZ_ARCHIVO_PING_URL", "").strip()
    if not destino or SECO:
        return
    try:
        url = "%s%sstatus=%s&msg=%s" % (
            destino,
            "&" if "?" in destino else "?",
            "up" if ok else "down",
            urllib.parse.quote((mensaje or ("ok" if ok else "fallo"))[:120]))
        urllib.request.urlopen(url, timeout=15).read()
    except Exception as e:
        # Que el aviso falle NO puede cambiar el resultado del archivo.
        log("aviso: no se pudo enviar el latido (%s)" % str(e)[:80])


def sql(q):
    return subprocess.check_output(
        ["docker", "exec", "postiz-postgres", "psql", "-U", "postiz", "-d", "postiz_db", "-tAc", q],
        timeout=120).decode("utf-8", "replace").strip()


def notion(u, d=None, m=None):
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        u, data=json.dumps(d).encode() if d else None, headers=NH, method=m), timeout=60).read())


def limpio(s, largo=70):
    """Nombre valido para una carpeta de Drive. Se conservan tildes y ñ."""
    s = unicodedata.normalize("NFC", (s or "").strip())
    s = re.sub(r"[/\\\r\n\t]", " ", s)          # / es separador de ruta
    s = re.sub(r"\s+", " ", s).strip(" .")
    return (s[:largo].strip() or "sin titulo")


def sin_html(s):
    s = re.sub(r"<br\s*/?>", "\n", s or "")
    s = re.sub(r"</p>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    for a, b in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#39;", "'"), ("&quot;", '"')]:
        s = s.replace(a, b)
    return s.strip()


def rclone(*args):
    r = subprocess.run(["rclone", *args, "--drive-root-folder-id", PUBLICADO_ID],
                       capture_output=True, text=True, timeout=900)
    return r.returncode, (r.stderr or "")[-300:]

