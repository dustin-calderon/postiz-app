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
import fcntl, sys

from archivo_drive_comun import SECO, latido, log, notion
from archivo_drive_fuentes import filas_notion, guardar_registro, publicados, registro_web
from archivo_drive_pieza import archivar, carpeta_de

CERROJO = "/opt/homeserver/scripts/.postiz-archivo.lock"  # no en /run/lock: alli (sticky, protected_regular) el cerrojo de otro usuario bloquea a root
_CERROJO = None


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
    latido(fallos == 0, "%d archivados, %d fallos" % (hechos, fallos))
    return 1 if fallos else 0


if __name__ == "__main__":
    try:
        codigo = main()
    except SystemExit as e:                     # p. ej. registro local ilegible
        codigo = e.code if isinstance(e.code, int) else 2
        latido(False, "abortado con codigo %s" % codigo)
    except Exception as e:
        log("ERROR FATAL: %s" % e)
        latido(False, "ERROR FATAL: %s" % str(e)[:120])
        codigo = 2
    sys.exit(codigo)
