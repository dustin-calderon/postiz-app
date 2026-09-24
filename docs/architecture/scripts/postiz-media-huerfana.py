# -*- coding: utf-8 -*-
"""Libera la media del pipeline que ya no es de nadie.

Una fila del calendario deja media sin dueño en Postiz cuando le cambian los
ficheros (el sync sube los nuevos y los anteriores se quedan), cuando se rehace
un carrusel replicado (sus láminas anteriores) o cuando se borra la fila. Nada
de eso lo recoge la limpieza de Postiz: su Phase 2 solo purga lo que ya está
marcado como borrado (MEDIA_CLEANUP_PIPELINE.md).

Esto lo marca. Un media se libera solo si se cumplen las cuatro:
  - lo usó al menos un post, y todos los que lo usaron los creó el pipeline
    (API): un media que no usó ningún post puede ser de la biblioteca de Postiz,
    y uno que usó un post hecho a mano es de quien lo hizo;
  - ningún post vivo lo usa;
  - ninguna fila de Notion lo apunta en `❌ postiz_media`, tenga el Status que
    tenga: es lo que el sync reutiliza cuando una fila aplazada o vaciada vuelve;
  - el último post que lo usó se borró hace más de un día.
Se marca con `DELETE /public/v1/media/:id`, que solo pone `deletedAt`: el
fichero lo quita la Phase 2 de Postiz a los 7 días, así que durante una semana
se deshace vaciando `deletedAt`.

    python3 postiz-media-huerfana.py          # libera
    python3 postiz-media-huerfana.py --seco   # solo dice qué liberaría

Solo lee Notion y la base de Postiz; lo único que escribe es ese DELETE.
Sale con código distinto de cero si algo falla: el cron lo manda al bus.
Copia viva: /opt/homeserver/scripts/postiz-media-huerfana.py.
"""
import json, os, subprocess, sys, urllib.request
from datetime import datetime

ORG = "30c506a6-0a2c-4661-95bb-abec2e14b3f2"
DS_NOTION = "186a2405-a123-81dc-832f-000b82a65c0c"  # fuente de datos del calendario (API 2025-09-03)
SECO = "--seco" in sys.argv
NH = {"Authorization": "Bearer " + os.environ["NOTION_API_KEY"], "Notion-Version": "2025-09-03",
      "Content-Type": "application/json"}


def log(msg):
    print("[%s] media-huerfana: %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def sql(q):
    return subprocess.check_output(
        ["docker", "exec", "postiz-postgres", "psql", "-U", "postiz", "-d", "postiz_db", "-tA", "-F", "|", "-c", q],
        timeout=120).decode("utf-8", "replace").strip()


def apuntada_en_notion():
    """Los ids de media que alguna fila apunta en ❌ postiz_media, sin filtro."""
    ids, cursor, filas = set(), None, 0
    while True:
        cuerpo = {"page_size": 100}
        if cursor:
            cuerpo["start_cursor"] = cursor
        r = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://api.notion.com/v1/data_sources/%s/query" % DS_NOTION,
            data=json.dumps(cuerpo).encode(), headers=NH, method="POST"), timeout=60).read())
        for p in r["results"]:
            filas += 1
            texto = "".join(t["plain_text"] for t in p["properties"]["❌ postiz_media"]["rich_text"])
            try:
                media = json.loads(texto) if texto else []
            except ValueError:
                # Si no se puede leer, no se sabe qué reclama: no se libera nada.
                raise SystemExit("la fila %s tiene un ❌ postiz_media ilegible" % p["id"])
            ids.update(m["id"] for m in media if isinstance(m, dict) and m.get("id"))
        if not r["has_more"]:
            break
        cursor = r["next_cursor"]
    # Una lista vacía por un fallo de permisos liberaría todo: se exige ver filas.
    if not filas:
        raise SystemExit("Notion no devolvió ninguna fila: no se libera nada")
    return ids, filas


def candidatos():
    filas = sql("""
        SELECT m.id, m.path FROM "Media" m
        WHERE m."organizationId" = '%s' AND m."deletedAt" IS NULL
          AND EXISTS (SELECT 1 FROM "Post" p WHERE p.image LIKE '%%' || m.path || '%%')
          AND NOT EXISTS (SELECT 1 FROM "Post" p WHERE p.image LIKE '%%' || m.path || '%%'
                          AND (p."deletedAt" IS NULL OR p."creationMethod" <> 'API'
                               OR p."deletedAt" > now() - interval '1 day'))""" % ORG)
    return [l.split("|", 1) for l in filas.splitlines() if l]


def api_key():
    k = sql("""SELECT "apiKey" FROM "Organization" WHERE id = '%s'""" % ORG)
    if not k:
        raise SystemExit("apiKey de Postiz vacía")
    return k


def main():
    en_notion, filas = apuntada_en_notion()
    libres = [(i, p) for i, p in candidatos() if i not in en_notion]
    log("%d filas de Notion apuntan %d media; %d media del pipeline sin dueño"
        % (filas, len(en_notion), len(libres)))
    if SECO:
        for i, p in libres:
            log("[seco] liberaría %s %s" % (i, p.rsplit("/", 1)[-1]))
        return 0
    clave, fallos = api_key(), 0
    for i, p in libres:
        req = urllib.request.Request("http://127.0.0.1:4007/api/public/v1/media/" + i,
                                     headers={"Authorization": clave}, method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=30).read()
        except Exception as e:
            fallos += 1
            log("no se pudo liberar %s: %s" % (i, str(e)[:120]))
    log("liberados %d · fallos %d" % (len(libres) - fallos, fallos))
    return 1 if fallos else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        if isinstance(e.code, str):
            log("ABORTADO: " + e.code)
            sys.exit(2)
        raise
