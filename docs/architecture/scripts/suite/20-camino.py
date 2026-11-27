# -*- coding: utf-8 -*-
# Parte de la batería: la ejecuta `suite-pruebas-postiz.py` en un espacio de nombres COMPARTIDO
# (lo que define una parte lo ven las siguientes). No se lanza suelta.
print(); print("=" * 62); print("3 · CAMINO COMPLETO (carrusel de 2)"); print("=" * 62)
subprocess.run("ffmpeg -y -f lavfi -i testsrc=size=1080x1080:rate=1 -t 1 -frames:v 1 /tmp/t1.jpg", shell=True, capture_output=True)
subprocess.run("ffmpeg -y -f lavfi -i testsrc=size=1080x1080:rate=1 -t 1 -frames:v 1 /tmp/t2.jpg", shell=True, capture_output=True)
f1, f2 = subir("t1.jpg"), subir("t2.jpg")
# La fecha se calcula desde hoy: fijarla a mano la deja fuera de la ventana de
# 15 dias en cuanto pasa el tiempo, y el sync la ignora con razon — un fallo
# del test que se lee como un fallo del pipeline.
d7 = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
pid = fila({"Status": {"select": {"name": "Listo"}}, "cuenta": {"select": {"name": "AMORISMO VOL III"}},
            "Tipo": {"select": {"name": "Carrusel"}},
            "Fecha": {"date": {"start": d7 + "T18:00:00.000+02:00"}},
            "copy": {"rich_text": [{"text": {"content": "Suite de pruebas."}}]},
            "first_comment": {"rich_text": [{"text": {"content": "#suite"}}]},
            "media": {"files": [{"type": "file_upload", "file_upload": {"id": f1}, "name": "t1.jpg"},
                                 {"type": "file_upload", "file_upload": {"id": f2}, "name": "t2.jpg"}]}})
esperar_indice([pid])
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
r = leer(pid)
check("Status pasa a Programado", r["Status"] == "Programado")
check("el post queda programado en Postiz (QUEUE)", bool(r["post_id"]) and estado_post(r["post_id"]) == "QUEUE")
check("escribe ❌ postiz_post_id", bool(r["post_id"]))
check("escribe ❌ postiz_media", r["media"].count("path") == 2, "(2 ficheros)")
check("❌ error_log queda vacío", not r["error"])
pid_post = r["post_id"]
# Si alguien quita `externalId` del nodo "Construir POST", el pipeline sigue
# funcionando y la proteccion contra duplicados desaparece SIN dar ningun
# error. Esta comprobacion es lo unico que lo delataria.
ext_real = sql('SELECT COALESCE("externalId", \'(vacio)\') FROM "Post" WHERE id=\'%s\';' % pid_post)
check("el post creado por el pipeline lleva la identidad de su fila", ext_real == pid, "(%s)" % ext_real)
fecha = sql('SELECT "publishDate" FROM "Post" WHERE id=\'%s\';' % pid_post)
check("zona horaria 18:00+02 → 16:00 UTC", "16:00:00" in fecha, "(%s)" % fecha)
com = sql('SELECT count(*) FROM "Post" WHERE "parentPostId"=\'%s\';' % pid_post)
check("crea el primer comentario", com == "1")

print(); print("=" * 62); print("4 · REINTENTO REUTILIZA EL MEDIA"); print("=" * 62)
media_antes = r["media"]
t0 = time.time(); hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN}); dt = time.time() - t0
r2 = leer(pid)
check("no vuelve a subir los ficheros", r2["media"] == media_antes, "(%.1fs)" % dt)
check("crea un post nuevo", r2["post_id"] != pid_post)
check("borra el anterior", sql('SELECT "deletedAt" IS NOT NULL FROM "Post" WHERE id=\'%s\';' % pid_post) == "t")
check("guarda qué ficheros subió, en su orden", [m.get("src") for m in json.loads(r2["media"])] == ficheros(pid))

print(); print("=" * 62); print("4b · OTROS FICHEROS SE VUELVEN A SUBIR"); print("=" * 62)
# Mismo número de ficheros, pero otros y en otro orden: si el sync solo contara
# cuántos hay, reutilizaría los ya subidos y publicaría las láminas viejas.
g1, g2 = subir("t2.jpg"), subir("t1.jpg")
api("https://api.notion.com/v1/pages/" + pid, {"properties": {"media": {"files": [
    {"type": "file_upload", "file_upload": {"id": g1}, "name": "t2.jpg"},
    {"type": "file_upload", "file_upload": {"id": g2}, "name": "t1.jpg"}]}}}, m="PATCH")
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
r3 = leer(pid)
check("con otros ficheros los vuelve a subir", r3["media"] != r2["media"] and r3["media"].count("path") == 2)
check("y guarda los nuevos, en su orden", [m.get("src") for m in json.loads(r3["media"] or "[]")] == ficheros(pid))

print(); print("=" * 62); print("5 · RETIRADA"); print("=" * 62)
# Se comparan los posts WEB VIVOS antes y despues. La version anterior hacia
# SELECT sobre todos los WEB en QUEUE —hoy son 7, seis ya borrados— y comparaba
# las 7 lineas con "t", asi que no podia pasar nunca.
web_antes = sql('SELECT id FROM "Post" WHERE "creationMethod"=\'WEB\' AND state=\'QUEUE\' AND "deletedAt" IS NULL ORDER BY id;')
vigente = leer(pid)["post_id"]
check("el post de la fila sigue vivo antes de retirar", sql('SELECT "deletedAt" IS NULL FROM "Post" WHERE id=\'%s\';' % vigente) == "t")
api("https://api.notion.com/v1/pages/" + pid, {"properties": {"Status": {"select": None}}}, m="PATCH")
hit(L + "postiz-retirada-ig", hdr={"X-Sync-Token": TOKEN})
check("retira el post huérfano", sql('SELECT "deletedAt" IS NOT NULL FROM "Post" WHERE id=\'%s\';' % vigente) == "t")
web_despues = sql('SELECT id FROM "Post" WHERE "creationMethod"=\'WEB\' AND state=\'QUEUE\' AND "deletedAt" IS NULL ORDER BY id;')
check("NO toca los posts creados a mano (WEB)", web_antes == web_despues,
      "(%d vivos antes, %d después)" % (len(web_antes.split()), len(web_despues.split())))
api("https://api.notion.com/v1/pages/" + pid, {"in_trash": True}, m="PATCH")

