# -*- coding: utf-8 -*-
# Parte de la batería: la ejecuta `suite-pruebas-postiz.py` en un espacio de nombres COMPARTIDO
# (lo que define una parte lo ven las siguientes). No se lanza suelta.
print(); print("=" * 62); print("6 · RUTA DE ERROR EN LA SUBIDA"); print("=" * 62)
# Un asset ilegible dentro de una fila de dos. Hasta el 2026-08-16 este era el
# fallo más peligroso del pipeline precisamente porque NO se veía: el IF de
# subida partía los N items del SSH en dos ramas vivas, n8n ejecutaba primero
# la buena y su excepción mataba la ejecución antes de que la rama de error
# escribiera nada. La fila se quedaba en su estado, sin `error_log`, y lo ya
# subido quedaba huérfano para siempre. Nada de eso rompía ningún check.
subprocess.run("ffmpeg -y -v error -f lavfi -i color=c=orange:s=1080x1350 -frames:v 1 /tmp/e1.jpg",
               shell=True, capture_output=True)
with open("/tmp/eroto.jpg", "wb") as f:
    f.write(b"esto no es una imagen, es texto plano\n" * 8)
e_ok, e_roto = subir("e1.jpg"), subir("eroto.jpg")
pid_e = fila({"Status": {"select": {"name": "Listo"}}, "cuenta": {"select": {"name": "CITEM"}},
              "Tipo": {"select": {"name": "Carrusel"}},
              "Fecha": {"date": {"start": d7 + "T19:00:00", "time_zone": "Europe/Madrid"}},
              "copy": {"rich_text": [{"text": {"content": "Suite de pruebas: ruta de error."}}]},
              "media": {"files": [{"type": "file_upload", "file_upload": {"id": e_ok}, "name": "e1.jpg"},
                                  {"type": "file_upload", "file_upload": {"id": e_roto}, "name": "eroto.jpg"}]}})
esperar_indice([pid_e])
t_e = sql("SELECT now();")
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
r_e = leer(pid_e)
check("un asset ilegible deja la fila en Error", r_e["Status"] == "Error", "(%s)" % r_e["Status"])
check("el error_log dice qué asset y por qué",
      "eroto.jpg" in r_e["error"] and "ABORTADO" in r_e["error"], "(%s)" % r_e["error"][:70])
check("no crea el post ni deja media a medias", not r_e["post_id"] and not r_e["media"])
# Las dos caras del huérfano, y hacen falta las dos. La primera prueba que el
# asset bueno LLEGÓ a subirse —sin ella la segunda pasaría sin haber probado
# nada— y que acabó reclamado; la segunda, que no queda ninguno vivo. Se
# excluye lo que use un post vivo por la misma razón que en la limpieza:
# contar todo lo reciente falla en falso tras actividad real del pipeline.
check("el asset bueno se subió y acabó reclamado",
      int(sql("""SELECT count(*) FROM "Media"
                 WHERE "createdAt" > '%s' AND "deletedAt" IS NOT NULL;""" % t_e)) >= 1)
check("no deja huérfanos vivos",
      sql("""SELECT count(*) FROM "Media" m WHERE m."createdAt" > '%s'
             AND m."deletedAt" IS NULL
             AND NOT EXISTS (SELECT 1 FROM "Post" p WHERE p."deletedAt" IS NULL
                             AND p.image::text LIKE '%%'||m.id||'%%');""" % t_e) == "0")
borrar(pid_e)

print(); print("=" * 62); print("6c · POSTIZ RECHAZA LA PIEZA: EL MOTIVO SE ENTIENDE"); print("=" * 62)
# Una fila que pasa las validaciones de n8n y que Postiz rechaza: copy de mas de
# 2200 caracteres. `❌ error_log` lo lee una persona: tiene que traer el motivo de
# Postiz en limpio —sin el JSON escapado ni el stack de axios— y decir que el
# fallo es de la fila (nodo «Formatear error» del subflow).
subprocess.run("ffmpeg -y -v error -f lavfi -i color=c=blue:s=1080x1350 -frames:v 1 /tmp/e3.jpg",
               shell=True, capture_output=True)
pid_r = fila({"Status": {"select": {"name": "Listo"}}, "cuenta": {"select": {"name": "CITEM"}},
              "Tipo": {"select": {"name": "Post"}},
              "Fecha": {"date": {"start": d7 + "T19:00:00", "time_zone": "Europe/Madrid"}},
              "copy": {"rich_text": [{"text": {"content": "Suite de pruebas: rechazo. " + "x" * 1900}},
                                     {"text": {"content": "y" * 400}}]},
              "media": {"files": [{"type": "file_upload", "file_upload": {"id": subir("e3.jpg")}, "name": "e3.jpg"}]}})
esperar_indice([pid_r])
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
r_r = leer(pid_r)
check("Postiz rechaza la pieza: la fila queda en Error", r_r["Status"] == "Error", "(%s)" % r_r["Status"])
check("el error_log trae el motivo de Postiz en limpio",
      r_r["error"].startswith("Postiz rechazó la pieza: post is too long")
      and "stack" not in r_r["error"] and '\\"' not in r_r["error"], "(%s)" % r_r["error"][:90])
check("el rechazo no crea el post ni deja media a medias", not r_r["post_id"] and not r_r["media"])
borrar(pid_r)

