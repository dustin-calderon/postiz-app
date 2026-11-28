# -*- coding: utf-8 -*-
"""De donde sale lo que hay que archivar: Postiz, Notion y el registro local."""
import json, os, tempfile

from archivo_drive_comun import DS_NOTION, REGISTRO_WEB, SECO, log, notion, sin_html, sql


# ── 1. Lo publicado, segun Postiz ──────────────────────────────────
def publicados():
    filas = sql("""SELECT p.id||'\x01'||p."publishDate"::text||'\x01'||coalesce(i.name,'?')
                   ||'\x01'||coalesce(p."integrationId",'')
                   ||'\x01'||coalesce(p."releaseURL",'')||'\x01'||replace(coalesce(p.content,''), E'\\n', '\x03')
                   ||'\x01'||coalesce(p.image::text,'[]')
                   FROM "Post" p LEFT JOIN "Integration" i ON i.id=p."integrationId"
                   WHERE p.state='PUBLISHED' AND p."parentPostId" IS NULL
                   ORDER BY p."publishDate";""")
    # psql -A separa los registros con \n y NO escapa los \n del contenido: un
    # copy con salto de linea partia su fila en dos y abortaba la pasada entera
    # (y con ella todos los posts posteriores). Por eso el SQL cambia \n por
    # \x03 dentro de content y aqui se restaura tras el split.
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
                    "url": url, "copy": sin_html(contenido.replace("\x03", "\n")),
                    "media": media})
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
        d = notion("https://api.notion.com/v1/data_sources/%s/query" % DS_NOTION, cuerpo, m="POST")
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
        # carpetas duplicadas en Drive que hay que limpiar a mano.
        #
        # El fichero se deja DONDE ESTA, a proposito. Apartarlo con marca de
        # tiempo salvaba esta pasada pero no la siguiente: sin fichero, la de
        # mañana vuelve a ser "primera ejecucion" y duplica igual. Solo retrasa
        # el problema un dia. Asi cada pasada aborta con el mismo aviso hasta
        # que una persona lo repare o lo borre, que es la unica salida que no
        # ensucia Drive.
        log("FALLO: registro local ilegible en %s (%s). No se archiva nada "
            "hasta que se repare o se borre a mano." % (REGISTRO_WEB, e))
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
