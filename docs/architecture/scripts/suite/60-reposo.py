# -*- coding: utf-8 -*-
# Parte de la batería: la ejecuta `suite-pruebas-postiz.py` en un espacio de nombres COMPARTIDO
# (lo que define una parte lo ven las siguientes). No se lanza suelta.
print(); print("=" * 62); print("7 · ESTADO EN REPOSO"); print("=" * 62)
c, r1 = hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
# Las filas de la suite ya estan archivadas: cualquier fila que aparezca en la
# respuesta es real. Una escritura en Notion (`"object":"page"`) o una fila que
# el planificador reporta (`"page_id"`, p. ej. «fuera de ventana») dicen que el
# calendario tiene contenido, y entonces «no hace nada» no se puede afirmar.
if '"object":"page"' in r1 or '"page_id"' in r1:
    omite("sync no hace nada", "calendario con filas reales")
else:
    check("sync no hace nada", "nada que hacer" in r1)
c, r2 = hit(L + "postiz-retirada-ig", hdr={"X-Sync-Token": TOKEN})
if '"object":"page"' in r2:
    omite("retirada no hace nada", "calendario con filas reales en ventana")
else:
    check("retirada no hace nada", "nada que hacer" in r2)
# Antes contaba TODOS los posts vivos en QUEUE de la base y esperaba
# exactamente 1, lo que mezclaba el estado de la suite con el contenido real
# del usuario: el 2026-08-05 fallaba con 38 posts programados de verdad, y
# luego con 0. La suite solo puede afirmar algo sobre SUS posts, que se
# reconocen por el copy que escribe fila().
resto = sql('SELECT count(*) FROM "Post" WHERE "deletedAt" IS NULL AND content LIKE \'%Suite de pruebas%\';')
check("la suite no deja posts suyos vivos", resto == "0", "(%s vivos)" % resto)

print(); print("=" * 62); print("8 · LIMPIEZA"); print("=" * 62)
# La bateria sube ficheros de prueba y borra los posts, pero los Media quedaban
# vivos y habia que barrerlos a mano. Se borran por la API publica —el mismo
# soft-delete que la UI—, no por SQL, para no divergir del camino real.
sueltos = [l for l in sql("""SELECT id FROM "Media" WHERE "deletedAt" IS NULL
                             AND "createdAt" > now() - interval '30 minutes';""").split() if l]
borrados = 0
for m in sueltos:
    usado = sql("""SELECT count(*) FROM "Post" WHERE "deletedAt" IS NULL AND image::text LIKE '%%%s%%';""" % m)
    if usado != "0":
        print("  conservo %s (lo usa un post vivo)" % m[:8]); continue
    try:
        urllib.request.urlopen(urllib.request.Request(
            "https://postiz.dustincalderon.com/api/public/v1/media/" + m,
            headers={"Authorization": APIK, "User-Agent": "curl/8.5.0"}, method="DELETE"))
        borrados += 1
    except Exception as e:
        print("  no se pudo borrar %s: %s" % (m[:8], e))
# Un media reciente que usa un post vivo NO es un medio suelto: contar todos
# los de <30 min fallaba en falso justo después de actividad real del
# pipeline (2026-08-15, el reel recuperado).
check("no deja medios de prueba sueltos",
      sql("""SELECT count(*) FROM "Media" m WHERE m."deletedAt" IS NULL
             AND m."createdAt" > now() - interval '30 minutes'
             AND NOT EXISTS (SELECT 1 FROM "Post" p WHERE p."deletedAt" IS NULL
                             AND p.image::text LIKE '%'||m.id||'%');""") == "0",
      "(%d borrados)" % borrados)

print(); print("=" * 62)
print("RESULTADO: %d pasan, %d fallan%s" % (len(ok), len(fail),
      ", %d omitidas" % len(omitidas) if omitidas else ""))
if fail:
    print("FALLAN:", ", ".join(fail)); sys.exit(1)
print("TODO CORRECTO")
