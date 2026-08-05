# -*- coding: utf-8 -*-
"""Archivo curado de lo publicado: Seagate -> Google Drive, con enlace en Notion.

    #POSTIZ/Publicado/<cuenta>/<AAAA-MM>/<AAAA-MM-DD titulo>/
        01.jpg  02.jpg  ...   (en el orden real del carrusel)
        post.txt              (copy, hora, enlace a Instagram, nombres originales)

Los BYTES salen del Seagate, no de Notion:
  - Notion no tiene el material anterior al pipeline (18 posts sin fila).
  - Leer de Notion haria que el archivo dependiera de la misma pieza de la que
    protege: si alguien archiva una fila antes del job, se pierde en las dos.
  - Verificado md5-identico al original de Notion en la primera publicacion real.

Los METADATOS salen de la base de Postiz (Post.image da el ORDEN real), que
cubre los 19 publicados. Notion solo aporta el titulo y recibe el enlace.

Registro de lo ya archivado:
  - Filas del pipeline -> propiedad `❌ drive_url` en Notion (ademas es el
    enlace de vuelta, asi que no es estado muerto).
  - Posts sin fila (los de la UI) -> fichero local, porque no hay donde anotarlo.
Para rearchivar algo: vaciar `❌ drive_url` (o borrarlo del fichero local).
"""
import fcntl, json, os, re, subprocess, sys, tempfile, unicodedata, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PUBLICADO_ID = "1RkW1J4lc2X-qmOTqrRsJwQc1uuDMMN6G"
REMOTO = "gdrive-work"
RAIZ_DISCO = "/mnt/seagate/postiz-media"
DB_NOTION = "186a2405a123812aa925cde1bb94ef12"
REGISTRO_WEB = "/opt/homeserver/scripts/.postiz-archivo-web.json"
CERROJO = "/var/lock/postiz-archivo.lock"
_CERROJO = None

# El nombre de la carpeta de cuenta se resuelve por integrationId, NO por
# Integration.name ni por la propiedad `cuenta` de Notion. Si no, el mismo canal
# genera dos carpetas: los posts hechos a mano dan "CITEM Conservatorio
# Iberoamericano..." y los del pipeline dan "CITEM", y el archivo de una cuenta
# queda partido en dos sitios. Son los mismos ids que usa el nodo Planificar.
CUENTAS = {
    "cmqjq77hg0001mw7y2xf6bg86": "Dustin Calderón",
    "cmqjqapu00003mw7yrudcwklj": "CITEM",
    "cmqjqfvnw0005mw7yoywgo6he": "AMORISMO VOL III",
    # TikTok. Se llama igual que la de Instagram ("Dustin Calderon"), asi que
    # sin un nombre distinto un cross-post generaria LA MISMA carpeta y el
    # segundo post machacaria los masters del primero.
    "cmqjs6xnx0001q07q9aohapuv": "Dustin Calderón (TikTok)",
}
LOG = "/var/log/postiz-archivo.log"
# publishDate se guarda en UTC. La zona se resuelve con la base de datos del
# sistema, NO con un desfase fijo: +2 solo vale en verano, y una carpeta
# fechada mal en noviembre es un error que no se detecta hasta que molesta.
MADRID = ZoneInfo("Europe/Madrid")
SECO = "--seco" in sys.argv

TOK = os.environ["NOTION_API_KEY"]
NH = {"Authorization": "Bearer " + TOK, "Notion-Version": "2022-06-28",
      "Content-Type": "application/json"}


def log(msg):
    linea = "[%s] archivo: %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(linea)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except IOError:
        pass


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


# ── 1. Lo publicado, segun Postiz ──────────────────────────────────
def publicados():
    filas = sql("""SELECT p.id||'\x01'||p."publishDate"::text||'\x01'||coalesce(i.name,'?')
                   ||'\x01'||coalesce(p."integrationId",'')
                   ||'\x01'||coalesce(p."releaseURL",'')||'\x01'||coalesce(p.content,'')
                   ||'\x01'||coalesce(p.image::text,'[]')
                   FROM "Post" p LEFT JOIN "Integration" i ON i.id=p."integrationId"
                   WHERE p.state='PUBLISHED' AND p."parentPostId" IS NULL
                   ORDER BY p."publishDate";""")
    out = []
    for ln in filas.split("\n"):
        if not ln.strip():
            continue
        pid, fecha, cuenta, integ, url, contenido, img = ln.split("\x01", 6)
        try:
            media = json.loads(img)
        except ValueError:
            media = []
        out.append({"id": pid, "fecha": fecha, "cuenta_larga": cuenta,
                    "integracion": integ,
                    "url": url, "copy": sin_html(contenido), "media": media})
    return out


# ── 2. Las filas de Notion que ya tienen post_id ───────────────────
def filas_notion():
    # Se pagina de verdad. Fallar al pasar de 100 seria una bomba de relojeria:
    # a ~140 publicaciones al año, el archivador dejaria de funcionar entero en
    # unos meses, y justo cuando ya hubiera material que perder.
    resultados, cursor = [], None
    while True:
        cuerpo = {"page_size": 100,
                  "filter": {"property": "❌ postiz_post_id", "rich_text": {"is_not_empty": True}}}
        if cursor:
            cuerpo["start_cursor"] = cursor
        d = notion("https://api.notion.com/v1/databases/%s/query" % DB_NOTION, cuerpo, m="POST")
        resultados.extend(d["results"])
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]
    por_post = {}
    for p in resultados:
        pr = p["properties"]
        t = lambda k: "".join(x["plain_text"] for x in pr[k]["rich_text"])
        titulo = pr["Name"]["title"]
        por_post[t("❌ postiz_post_id")] = {
            "page_id": p["id"],
            "titulo": titulo[0]["plain_text"] if titulo else "",
            "cuenta": (pr["cuenta"].get("select") or {}).get("name") or "",
            "tipo": (pr["Tipo"].get("select") or {}).get("name") or "",
            "first_comment": t("first_comment"),
            "media": pr["media"]["files"],
            "drive_url": pr["❌ drive_url"].get("url") or "",
        }
    return por_post


def registro_web():
    try:
        with open(REGISTRO_WEB, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}                       # primera ejecucion: no hay nada anotado
    except (IOError, ValueError) as e:
        # Un registro ilegible NO es un registro vacio. Devolver {} hacia creer
        # que no se habia archivado nada y volvia a subir las 19 piezas, creando
        # carpetas duplicadas en Drive. Se aparta y se aborta: es preferible una
        # noche sin archivar, que se recupera sola, a un Drive que hay que
        # limpiar a mano.
        roto = "%s.roto-%s" % (REGISTRO_WEB, datetime.now().strftime("%Y%m%d%H%M%S"))
        try:
            os.replace(REGISTRO_WEB, roto)
        except OSError:
            roto = "(no se pudo apartar)"
        log("FALLO: registro local ilegible (%s). Apartado en %s. No se archiva "
            "nada esta pasada; revisalo antes de repetir." % (e, roto))
        raise SystemExit(2)


def guardar_registro(reg):
    if SECO:
        return
    # Escritura atomica. `open(..., "w")` trunca antes de escribir, asi que una
    # muerte a mitad dejaba el JSON cortado, que es justo el caso de arriba.
    # El temporal va en el MISMO directorio a proposito: os.replace solo es
    # atomico dentro del mismo sistema de ficheros.
    destino = os.path.dirname(REGISTRO_WEB) or "."
    fd, tmp = tempfile.mkstemp(dir=destino, prefix=".postiz-archivo-web.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())        # sin esto el rename puede adelantar a los datos
        os.chmod(tmp, 0o664)            # mkstemp da 0600; el fichero era 664
        os.replace(tmp, REGISTRO_WEB)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── 3. Nombre de la carpeta ────────────────────────────────────────
def carpeta_de(post, fila):
    """<cuenta>/<AAAA-MM>/<AAAA-MM-DD titulo>"""
    dt = datetime.strptime(post["fecha"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    loc = dt.astimezone(MADRID)
    cuenta = CUENTAS.get(post["integracion"])
    if not cuenta:
        # Canal no registrado en el mapa: se recorta el nombre y se avisa, para
        # que no pase inadvertido que hay una integracion nueva que anadir.
        cuenta = post["cuenta_larga"].split("|")[0].strip()
        cuenta = " ".join(cuenta.split()[:2]) if len(cuenta) > 24 else cuenta
        log("  AVISO: integracion %r fuera del mapa, uso %r" % (post["integracion"][:10], cuenta))
    if fila and fila["titulo"]:
        titulo = fila["titulo"]
    else:
        primeras = " ".join(post["copy"].split()[:6])
        titulo = primeras or loc.strftime("%H%M")
    return "%s/%s/%s %s" % (limpio(cuenta, 40), loc.strftime("%Y-%m"),
                            loc.strftime("%Y-%m-%d"), limpio(titulo)), loc


# ── 4. post.txt ────────────────────────────────────────────────────
def texto_del_post(post, fila, loc, ficheros, perdidos):
    L = []
    L.append("Pieza:      %s" % (fila["titulo"] if fila and fila["titulo"] else "(sin titulo en Notion)"))
    L.append("Cuenta:     %s" % post["cuenta_larga"])
    L.append("Publicado:  %s (Europe/Madrid)" % loc.strftime("%Y-%m-%d %H:%M"))
    L.append("Instagram:  %s" % (post["url"] or "(sin permalink guardado)"))
    if fila:
        L.append("Tipo:       %s" % (fila["tipo"] or "-"))
        L.append("Notion:     https://www.notion.so/%s" % fila["page_id"].replace("-", ""))
    else:
        L.append("Origen:     creado a mano en la UI de Postiz (sin fila en Notion)")
    L.append("Post ID:    %s" % post["id"])
    L.append("")
    L.append("--- copy ---")
    L.append(post["copy"] or "(vacio)")
    L.append("")
    L.append("--- primer comentario ---")
    L.append((fila["first_comment"] if fila and fila["first_comment"] else "(ninguno)"))
    L.append("")
    L.append("--- ficheros, en orden de carrusel ---")
    for destino, origen, nombre_notion, tam in ficheros:
        orig = ("  <-  %s" % nombre_notion) if nombre_notion else ""
        L.append("%-8s %12d B%s" % (destino, tam, orig))
    if perdidos:
        L.append("")
        L.append("--- FICHEROS PERDIDOS ---")
        L.append("Estos ya no estaban en el disco cuando se archivo esta pieza.")
        L.append("Se publicaron, pero la purga de la cache se los llevo antes de que")
        L.append("existiera este archivo. No hay copia en ningun sitio.")
        for p in perdidos:
            L.append("  %s" % p)
    return "\n".join(L) + "\n"


# ── 5. Archivar una pieza ──────────────────────────────────────────
def archivar(post, fila):
    carpeta, loc = carpeta_de(post, fila)
    nombres_notion = [f.get("name", "") for f in (fila["media"] if fila else [])]

    ficheros, perdidos = [], []
    for i, m in enumerate(post["media"]):
        ruta = m.get("path", "")
        if "/uploads/" not in ruta:
            continue
        local = os.path.join(RAIZ_DISCO, ruta.split("/uploads/")[1])
        ext = os.path.splitext(local)[1].lower() or ".bin"
        destino = "%02d%s" % (i + 1, ext)
        nombre_notion = nombres_notion[i] if i < len(nombres_notion) else ""
        if os.path.isfile(local):
            ficheros.append((destino, local, nombre_notion, os.path.getsize(local)))
        else:
            perdidos.append("%s (era %s)" % (destino, os.path.basename(local)))

    if SECO:
        return "", len(ficheros), len(perdidos)

    # GUARDA DE COLISION. El nombre de carpeta no es unico por construccion:
    # dos piezas de la misma cuenta, el mismo dia y con titulos que truncan
    # igual producen la misma ruta. Sin esto `copyto` SOBRESCRIBE los masters
    # de la primera y el resumen dice "0 fallos". Mejor fallar a las claras.
    ya = subprocess.run(["rclone", "cat", "%s:%s/post.txt" % (REMOTO, carpeta),
                         "--drive-root-folder-id", PUBLICADO_ID],
                        capture_output=True, text=True, timeout=300)
    if ya.returncode == 0 and ya.stdout.strip():
        duenno = ""
        for ln in ya.stdout.splitlines():
            if ln.startswith("Post ID:"):
                duenno = ln.split(":", 1)[1].strip()
        if duenno and duenno != post["id"]:
            raise RuntimeError(
                "COLISION: la carpeta %r ya es del post %s. No se sobrescribe. "
                "Renombra una de las dos piezas en Notion." % (carpeta, duenno))

    rc, err = rclone("mkdir", "%s:%s" % (REMOTO, carpeta))
    if rc != 0:
        raise RuntimeError("no se pudo crear %r: %s" % (carpeta, err))

    for destino, local, _n, _t in ficheros:
        rc, err = rclone("copyto", local, "%s:%s/%s" % (REMOTO, carpeta, destino))
        if rc != 0:
            raise RuntimeError("fallo copiando %s: %s" % (destino, err))

    tmp = "/tmp/_post_%s.txt" % post["id"]
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(texto_del_post(post, fila, loc, ficheros, perdidos))
    rc, err = rclone("copyto", tmp, "%s:%s/post.txt" % (REMOTO, carpeta))
    os.unlink(tmp)
    if rc != 0:
        raise RuntimeError("fallo copiando post.txt: %s" % err)

    # VERIFICACION: que rclone salga con 0 no prueba que este. Se relee.
    r = subprocess.run(["rclone", "lsf", "%s:%s" % (REMOTO, carpeta),
                        "--drive-root-folder-id", PUBLICADO_ID],
                       capture_output=True, text=True, timeout=300)
    presentes = set(x.strip() for x in r.stdout.split("\n") if x.strip())
    esperados = set(d for d, _l, _n, _t in ficheros) | {"post.txt"}
    faltan = esperados - presentes
    if faltan:
        raise RuntimeError("tras copiar, faltan en Drive: %s" % sorted(faltan))
    # Y lo que SOBRA: si una pasada anterior dejo 6 ficheros y esta sube 3, los
    # tres viejos siguen dentro mezclados con los nuevos. Mirar solo lo que
    # falta no lo detecta nunca.
    sobran = presentes - esperados
    if sobran:
        raise RuntimeError("en Drive sobran ficheros de otra pieza o pasada: %s" % sorted(sobran))

    ids = subprocess.run(["rclone", "lsjson", "--dirs-only",
                          "%s:%s" % (REMOTO, os.path.dirname(carpeta)),
                          "--drive-root-folder-id", PUBLICADO_ID],
                         capture_output=True, text=True, timeout=300)
    fid = ""
    try:
        for x in json.loads(ids.stdout):
            if x["Name"] == os.path.basename(carpeta):
                fid = x["ID"]
    except ValueError:
        pass
    if not fid:
        # Sin ID no hay enlace, y sin enlace la pieza queda marcada como NO
        # archivada: se volveria a subir entera cada noche, en silencio. Mejor
        # que falle a las claras y se vea en el log.
        raise RuntimeError("no se pudo leer el ID de la carpeta %r en Drive" % carpeta)
    return "https://drive.google.com/drive/folders/%s" % fid, len(ficheros), len(perdidos)


# ── 6. Bucle principal ─────────────────────────────────────────────
def main():
    # Una sola instancia: una pasada con muchas piezas nuevas puede tardar mas
    # que el hueco hasta la siguiente, y dos a la vez se pisarian escribiendo
    # las mismas carpetas.
    global _CERROJO
    _CERROJO = open(CERROJO, "w")
    try:
        fcntl.flock(_CERROJO, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("ya hay una pasada en ejecucion, salgo")
        return 0

    if SECO:
        log("=== PASADA EN SECO: no se escribe en Drive ni en Notion ===")

    posts = publicados()
    filas = filas_notion()
    reg = registro_web()
    log("%d publicados en Postiz · %d filas de Notion con post_id · %d en el registro local"
        % (len(posts), len(filas), len(reg)))

    hechos = saltados = fallos = sin_ficheros = 0
    for post in posts:
        fila = filas.get(post["id"])

        ya = fila["drive_url"] if fila else reg.get(post["id"], {}).get("url", "")
        if ya:
            saltados += 1
            continue
        if not post["media"]:
            sin_ficheros += 1
            continue

        try:
            url, n_ok, n_perd = archivar(post, fila)
        except Exception as e:
            fallos += 1
            log("  FALLO %s: %s" % (post["id"][:10], str(e)[:200]))
            continue

        carpeta, _loc = carpeta_de(post, fila)
        aviso = ("  (%d PERDIDOS)" % n_perd) if n_perd else ""
        log("  %s %s -> %s · %d fichero(s)%s"
            % ("[seco]" if SECO else "OK", post["id"][:10], carpeta, n_ok, aviso))
        hechos += 1

        if SECO:
            continue
        if fila:
            try:
                notion("https://api.notion.com/v1/pages/" + fila["page_id"],
                       {"properties": {"❌ drive_url": {"url": url or None}}}, m="PATCH")
                comp = notion("https://api.notion.com/v1/pages/" + fila["page_id"])
                escrito = comp["properties"]["❌ drive_url"].get("url") or ""
                if escrito != url:
                    fallos += 1
                    hechos -= 1
                    log("  FALLO: Notion no guardo el enlace de %s (leido: %r)" % (post["id"][:10], escrito))
            except Exception as e:
                # Contaba como exito: `hechos` ya estaba incrementado y esto
                # solo avisaba. El resumen decia "0 fallos" mientras la pieza
                # quedaba sin marcar y se resubia entera cada noche.
                fallos += 1
                hechos -= 1
                log("  FALLO al escribir ❌ drive_url en %s: %s" % (post["id"][:10], str(e)[:120]))
        else:
            reg[post["id"]] = {"url": url, "carpeta": carpeta,
                               "fecha": post["fecha"][:19], "perdidos": n_perd}
            guardar_registro(reg)

    log("resumen: %d archivados · %d ya estaban · %d sin ficheros · %d fallos"
        % (hechos, saltados, sin_ficheros, fallos))
    return 1 if fallos else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("ERROR FATAL: %s" % e)
        sys.exit(2)
