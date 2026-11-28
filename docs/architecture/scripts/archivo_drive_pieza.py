# -*- coding: utf-8 -*-
"""Archivar una pieza: nombre de carpeta, post.txt y subida a Drive con su verificacion."""
import json, os, subprocess
from datetime import datetime, timezone

from archivo_drive_comun import MADRID, PUBLICADO_ID, RAIZ_DISCO, REMOTO, SECO, limpio, log, rclone
from archivo_drive_cuentas import CUENTAS


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
