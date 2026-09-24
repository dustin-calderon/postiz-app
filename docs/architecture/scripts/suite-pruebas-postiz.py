# -*- coding: utf-8 -*-
"""Batería de pruebas del pipeline. No publica nada en Instagram."""
import json, urllib.request, os, re, uuid, subprocess, time, sys, datetime, threading

TOK = os.environ["NOTION_API_KEY"]
TOKEN = os.environ["N8N_SYNC_IG_TOKEN"]
BTN = os.environ["N8N_SYNC_IG_BUTTON_PATH"]
RECV = os.environ["N8N_POSTIZ_WEBHOOK_PATH"]
DB = "186a2405a123812aa925cde1bb94ef12"
W = "https://auto.dustincalderon.com/webhook/"
# Lo que espera a que acabe una pasada va a n8n desde el propio Beelink, sin
# Cloudflare: Cloudflare corta a los 125 s una respuesta que no llega (524), y una
# pasada con bastantes filas, o que espera turno, los pasa; se leería el
# resultado antes de tiempo. Por W solo va lo que prueba el camino público.
L = "http://127.0.0.1:5678/webhook/"
H = {"Authorization": "Bearer " + TOK, "Notion-Version": "2022-06-28"}
ok = []; fail = []; omitidas = []

def api(u, d=None, m=None, h=None, raw=False):
    hh = dict(H)
    if h: hh.update(h)
    if d is not None and not raw:
        d = json.dumps(d).encode(); hh["Content-Type"] = "application/json"
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, data=d, headers=hh, method=m)).read())

def hit(url, body="{}", hdr=None):
    # El User-Agent NO es opcional: Cloudflare bloquea `Python-urllib` en este
    # dominio y devuelve 403 sin que la peticion llegue a n8n (CONTENT_PIPELINE_POSTIZ_FORK.md §1). Sin esto
    # la bateria entera falla —y los checks que esperan 403 PASAN por el motivo
    # equivocado, que es peor.
    h = {"Content-Type": "application/json", "User-Agent": "curl/8.5.0"}
    if hdr: h.update(hdr)
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, data=body.encode(), headers=h, method="POST"))
        return r.status, r.read().decode()[:160]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:160]

def de_n8n(cuerpo):
    """Un 403 de n8n trae JSON; uno de Cloudflare trae una pagina HTML."""
    return "<html" not in cuerpo.lower() and "cloudflare" not in cuerpo.lower()

def sql(q):
    return subprocess.check_output(['docker','exec','postiz-postgres','psql','-U','postiz','-d','postiz_db','-tAc',q]).decode().strip()

def n8n_sql(q):
    return subprocess.check_output(['docker','exec','postgres_core','psql','-U','postgres','-d','n8n_db','-tAc',q]).decode().strip()

def check(nombre, cond, detalle=""):
    (ok if cond else fail).append(nombre)
    print("  %s %s %s" % ("PASA " if cond else "FALLA", nombre, detalle))

def omite(nombre, motivo):
    """Una comprobación que HOY no puede afirmarse no es una que falla.
    Contarla como fallo entrena a ignorar la suite (2026-08-15: los checks de
    reposo fallaban en falso con 7 filas reales programadas en ventana)."""
    omitidas.append(nombre)
    print("  OMITE %s (%s)" % (nombre, motivo))

def subir(nombre):
    fu = api("https://api.notion.com/v1/file_uploads", {"filename": nombre, "content_type": "image/jpeg"})
    b = "----" + uuid.uuid4().hex
    body = open("/tmp/" + nombre, "rb").read()
    parts = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\nContent-Type: image/jpeg\r\n\r\n" % (b, nombre)).encode() + body + ("\r\n--%s--\r\n" % b).encode()
    api(fu["upload_url"], parts, h={"Content-Type": "multipart/form-data; boundary=" + b}, raw=True)
    return fu["id"]

def fila(props):
    base = {"Name": {"title": [{"text": {"content": "__ZZ suite (borrar)"}}]},
            "Plataforma": {"multi_select": [{"name": "Instagram"}]}}
    base.update(props)
    return api("https://api.notion.com/v1/pages", {"parent": {"database_id": DB}, "properties": base})["id"]

def esperar_indice(pids, intentos=12):
    """El indice de consulta de Notion va por detras de la escritura: una fila
    recien creada tarda unos segundos en aparecer en /databases/{id}/query.
    Sin esta espera el sync no las ve y la suite falla por un motivo falso."""
    q = {"page_size": 100, "filter": {"property": "Name", "title": {"contains": "__ZZ suite"}}}
    for i in range(intentos):
        vistos = {r["id"] for r in api("https://api.notion.com/v1/databases/%s/query" % DB, q, m="POST")["results"]}
        if all(p in vistos for p in pids):
            print("  (indice de Notion al dia tras %ds)" % (i * 2))
            return True
        time.sleep(2)
    print("  AVISO: el indice de Notion no reflejo las %d filas en %ds" % (len(pids), intentos * 2))
    return False

def leer(pid):
    p = api("https://api.notion.com/v1/pages/" + pid)["properties"]
    t = lambda k: "".join(x["plain_text"] for x in p[k]["rich_text"])
    return {"Status": (p["Status"].get("select") or {}).get("name"),
            "post_id": t("❌ postiz_post_id"), "media": t("❌ postiz_media"),
            "error": t("❌ error_log"), "url": p["❌ release_url"].get("url")}

def ficheros(pid):
    """El id de cada fichero de `media` en Notion, en orden. Es lo que el sync
    guarda como `src` en `❌ postiz_media` para saber si puede reutilizarlo."""
    fs_ = api("https://api.notion.com/v1/pages/" + pid)["properties"]["media"]["files"]
    return [re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                       f["file"]["url"].split("?")[0])[-1] for f in fs_]

def borrar(pid):
    for b in ({"properties": {"Status": {"select": None}}}, {"archived": True}):
        api("https://api.notion.com/v1/pages/" + pid, b, m="PATCH")

# Clave de la API publica de Postiz. Vive aqui y no en la seccion de limpieza
# porque la 6b tambien crea posts por la API.
APIK = sql('SELECT "apiKey" FROM "Organization" WHERE id=\'30c506a6-0a2c-4661-95bb-abec2e14b3f2\';')

print("=" * 62); print("1 · SEGURIDAD DE LOS DISPARADORES"); print("=" * 62)
c, b = hit(W + "postiz-sync-ig")
check("sync sin token rechaza", c == 403 and de_n8n(b), "(%d, %s)" % (c, "de n8n" if de_n8n(b) else "DE CLOUDFLARE — no llego a n8n"))
c, b = hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": "malo"})
check("sync con token erróneo rechaza", c == 403 and de_n8n(b), "(%d, %s)" % (c, "de n8n" if de_n8n(b) else "DE CLOUDFLARE — no llego a n8n"))
c, r = hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN}); check("sync con token correcto acepta", c == 200, "(%d)" % c)
c, _ = hit(W + "postiz-sync-0000000000000000"); check("ruta secreta errónea rechaza", c == 404, "(%d)" % c)
# El botón responde 202 al instante y la pasada sigue por detrás. Notion corta
# la petición mucho antes que el túnel (medido el 2026-08-16: pasadas de 21 s
# pasaban y de 37 s ya no) y además descarta el cuerpo, así que esperar no
# aportaba nada y rompía el botón en cuanto la ventana traía varias filas.
# Lo que se afirma no es el resultado de la pasada —eso se ve en Notion— sino
# que la respuesta es inmediata: si alguien devuelve el webhook a "lastNode",
# este check lo caza. La ruta con cabecera sigue siendo síncrona a propósito.
t_btn = time.time()
c, r = hit(W + BTN, '{"source":{"type":"automation"}}')
dt_btn = time.time() - t_btn
check("botón de Notion responde al instante", c == 202 and '"ok":true' in r and dt_btn < 5,
      "(%d, %.2fs)" % (c, dt_btn))
c, _ = hit(W + RECV, "[]"); check("receptor acepta payload vacío", c == 200, "(%d)" % c)

print(); print("=" * 62); print("1b · LAS PASADAS DEL SYNC VAN DE UNA EN UNA"); print("=" * 62)
# Dos pasadas a la vez deciden cada una con lo que leyeron al empezar y pueden
# pisarse. El sync pregunta su turno al Beelink (turno-sync.sh) antes de leer
# Notion: si alguien conectara un disparador directo a la lectura, todo seguiría
# funcionando y las pasadas volverían a solaparse sin ningún error. Se lanzan dos
# con 3 s de diferencia: en fila, la segunda acaba una pasada entera después.
SYNC_WF = "eKxZPM4zjwhNb3vf"
def pasadas_en_marcha(desde_id=0):
    return n8n_sql("""SELECT count(*) FROM execution_entity WHERE "workflowId"='%s' AND id > %s
                      AND status IN ('new','running','waiting');""" % (SYNC_WF, desde_id))
# La del botón de la sección 1 sigue por detrás: con ella en marcha, la primera
# pasada de la prueba esperaría su turno y su duración no sería la de una pasada.
for _ in range(60):
    if pasadas_en_marcha() == "0": break
    time.sleep(5)
desde = n8n_sql("""SELECT coalesce(max(id), 0) FROM execution_entity WHERE "workflowId"='%s';""" % SYNC_WF)
hilos = []
for _ in range(2):
    hilos.append(threading.Thread(target=hit, args=(L + "postiz-sync-ig",), kwargs={"hdr": {"X-Sync-Token": TOKEN}}))
    hilos[-1].start(); time.sleep(3)
for h in hilos: h.join()
for _ in range(60):
    if pasadas_en_marcha(desde) == "0": break
    time.sleep(5)
pasadas = [l.split("|") for l in n8n_sql("""SELECT status, extract(epoch FROM "startedAt"), extract(epoch FROM "stoppedAt")
    FROM execution_entity WHERE "workflowId"='%s' AND id > %s ORDER BY id;""" % (SYNC_WF, desde)).splitlines() if l]
if len(pasadas) != 2:
    omite("la segunda pasada espera a la primera", "hubo %d pasadas, no las 2 de la prueba" % len(pasadas))
else:
    (e1, i1, f1), (e2, i2, f2) = [(e, float(i), float(f)) for e, i, f in pasadas]
    # En fila, la 2ª acaba una pasada entera después de la 1ª; solapadas, unos
    # 3 s después. Con pasadas de pocos segundos (calendario casi vacío) las dos
    # cosas se parecen demasiado para afirmar nada.
    if f1 - i1 < 30:
        omite("la segunda pasada espera a la primera", "la pasada duró %.0f s: muy poco para distinguir" % (f1 - i1))
    else:
        check("la segunda pasada espera a la primera", e1 == e2 == "success" and f2 - f1 > (f1 - i1) / 2,
              "(%s y %s; la 2ª acaba %.0f s después, la 1ª duró %.0f s)" % (e1, e2, f2 - f1, f1 - i1))

print(); print("=" * 62); print("2 · VALIDACIONES QUE DEBEN DAR Error"); print("=" * 62)
casos = [
 ("fecha sin hora",   {"Status": {"select": {"name": "Listo"}}, "cuenta": {"select": {"name": "CITEM"}},
                       "copy": {"rich_text": [{"text": {"content": "x"}}]},
                       "Fecha": {"date": {"start": "2026-08-20"}}}, "HORA"),
 ("sin ficheros",     {"Status": {"select": {"name": "Listo"}}, "cuenta": {"select": {"name": "CITEM"}},
                       "copy": {"rich_text": [{"text": {"content": "x"}}]},
                       "Fecha": {"date": {"start": "2026-08-20T10:00:00.000+02:00"}}}, "sin media"),
 ("sin cuenta",       {"Status": {"select": {"name": "Listo"}},
                       "copy": {"rich_text": [{"text": {"content": "x"}}]},
                       "Fecha": {"date": {"start": "2026-08-20T10:00:00.000+02:00"}}}, "sin cuenta"),
 ("sin copy",         {"Status": {"select": {"name": "Listo"}}, "cuenta": {"select": {"name": "CITEM"}},
                       "Fecha": {"date": {"start": "2026-08-20T10:00:00.000+02:00"}}}, "sin copy"),
]
pids = []
for nombre, props, esperado in casos:
    pid = fila(props); pids.append(pid)
esperar_indice(pids)
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
for (nombre, _, esperado), pid in zip(casos, pids):
    r = leer(pid)
    check(nombre + " → Error", r["Status"] == "Error", "motivo: " + r["error"][:60])
    # el motivo tiene que nombrar la propiedad tal y como se llama HOY en Notion
    check(nombre + " → motivo nombra la propiedad real", esperado in r["error"], "(esperaba %r)" % esperado)
for pid in pids: borrar(pid)

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

print(); print("=" * 62); print("3b · EL MARGEN NO SE COME LAS FILAS NUEVAS"); print("=" * 62)
# Regresion: el margen (5 min desde el 2026-08-15; antes 2 h) protege el
# borrar-y-recrear. Aplicado tambien a filas nuevas, una aprobada para dentro
# del margen se salta en cada pasada —la fecha solo se acerca— y no se crea
# nunca. La fila va a +4 min para caer DENTRO del margen actual.
# modo=borrador a proposito: la fecha cae en minutos y un QUEUE saldria
# publicado de verdad a Instagram si la limpieza fallara. El margen se evalua
# en `Planificar`, antes de que `modo` importe, asi que la regresion se prueba
# igual con riesgo cero.
dentro = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=4))
f3 = subir("t1.jpg")
pid_m = fila({"Status": {"select": {"name": "Listo"}}, "cuenta": {"select": {"name": "AMORISMO VOL III"}},
              "modo": {"select": {"name": "borrador"}},
              "Fecha": {"date": {"start": dentro.isoformat()}},
              "copy": {"rich_text": [{"text": {"content": "Dentro del margen."}}]},
              "media": {"files": [{"type": "file_upload", "file_upload": {"id": f3}, "name": "t1.jpg"}]}})
esperar_indice([pid_m])
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
rm_ = leer(pid_m)
check("fila NUEVA dentro del margen SÍ se crea", rm_["Status"] == "En Postiz (borrador)" and bool(rm_["post_id"]),
      "(Status=%s)" % rm_["Status"])
if rm_["post_id"]:
    check("y es DRAFT, no publica", sql('SELECT state FROM "Post" WHERE id=\'%s\';' % rm_["post_id"]) == "DRAFT")
if rm_["post_id"]:
    # ...y una segunda pasada ya NO la toca, porque ahora sí tiene post_id
    hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
    r_m2 = leer(pid_m)
    check("y en la 2ª pasada ya no se recrea", r_m2["post_id"] == rm_["post_id"], "(mismo post_id)")
    check("sigue viva en Postiz", sql('SELECT "deletedAt" IS NULL FROM "Post" WHERE id=\'%s\';' % rm_["post_id"]) == "t")
api("https://api.notion.com/v1/pages/" + pid_m, {"properties": {"Status": {"select": None}}}, m="PATCH")
hit(L + "postiz-retirada-ig", hdr={"X-Sync-Token": TOKEN})
if rm_["post_id"]:
    vivo = sql('SELECT "deletedAt" IS NULL FROM "Post" WHERE id=\'%s\';' % rm_["post_id"])
    check("la retirada SÍ respeta el margen (no la borra)", vivo == "t", "(sigue viva, correcto)")
    sql('UPDATE "Post" SET "deletedAt"=now() WHERE id=\'%s\';' % rm_["post_id"])  # limpieza manual
api("https://api.notion.com/v1/pages/" + pid_m, {"archived": True}, m="PATCH")

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
api("https://api.notion.com/v1/pages/" + pid, {"archived": True}, m="PATCH")

print(); print("=" * 62); print("5b · APLAZAR MÁS DE 15 DÍAS RETIRA EL POST"); print("=" * 62)
# Una pieza ya en Postiz cuya Fecha pasa a más de 15 días: el sync no la toca
# hasta que la nueva fecha entre en la ventana, así que su post es el de la
# fecha vieja y, si la fila lo reclamara, saldría igual. Borrador a propósito:
# no puede publicar nada.
pid_a = fila({"Status": {"select": {"name": "Listo"}}, "cuenta": {"select": {"name": "AMORISMO VOL III"}},
              "modo": {"select": {"name": "borrador"}},
              "Fecha": {"date": {"start": d7 + "T20:00:00.000+02:00"}},
              "copy": {"rich_text": [{"text": {"content": "Suite de pruebas: aplazada."}}]},
              "media": {"files": [{"type": "file_upload", "file_upload": {"id": subir("t1.jpg")}, "name": "t1.jpg"}]}})
esperar_indice([pid_a])
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
ra = leer(pid_a)
check("la pieza está en Postiz antes de aplazarla", ra["Status"] == "En Postiz (borrador)" and bool(ra["post_id"]), "(%s)" % ra["Status"])
d30 = (datetime.date.today() + datetime.timedelta(days=30)).isoformat() + "T20:00:00.000+02:00"
api("https://api.notion.com/v1/pages/" + pid_a, {"properties": {"Fecha": {"date": {"start": d30}}}}, m="PATCH")
q = {"page_size": 10, "filter": {"property": "Fecha", "date": {"after": (datetime.date.today() + datetime.timedelta(days=20)).isoformat()}}}
for _ in range(12):  # el índice de consulta de Notion va por detrás de la escritura
    if any(x["id"] == pid_a for x in api("https://api.notion.com/v1/databases/%s/query" % DB, q, m="POST")["results"]): break
    time.sleep(2)
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})  # el sync lanza la retirada
if ra["post_id"]:
    check("aplazarla retira el post de la fecha vieja", sql('SELECT "deletedAt" IS NOT NULL FROM "Post" WHERE id=\'%s\';' % ra["post_id"]) == "t")
check("y la fila vuelve a Listo", leer(pid_a)["Status"] == "Listo", "(%s)" % leer(pid_a)["Status"])
borrar(pid_a)

print(); print("=" * 62); print("6 · RUTA DE ERROR EN LA SUBIDA"); print("=" * 62)
# Un asset ilegible dentro de una fila de dos. Hasta el 2026-08-16 este era el
# fallo más peligroso del pipeline precisamente porque NO se veía: el IF de
# subida partía los N items del SSH en dos ramas vivas, n8n ejecutaba primero
# la buena y su excepción mataba la ejecución antes de que la rama de error
# escribiera nada. La fila se quedaba en `Listo`, sin `error_log`, y lo ya
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

print(); print("=" * 62); print("6b · IDENTIDAD EXTERNA: EL DUPLICADO ES IMPOSIBLE"); print("=" * 62)
# El 2026-08-24 dos pasadas del sync se solaparon 8 s y dejaron seis posts
# duplicados: cada una creo el suyo, la ultima escritura en Notion piso a la
# otra, y el post de la perdedora quedo vivo sin que ninguna fila lo reclamara.
#
# La cura no es serializar las pasadas —eso es contencion, la ventana sigue
# ahi— sino que crear sea idempotente: `externalId` viaja DENTRO del post, se
# graba de forma atomica con el, y una segunda creacion con la misma identidad
# devuelve la que ya existe en vez de acunar otra.
#
# Esta prueba solo vale si las dos peticiones se solapan DE VERDAD. Por eso
# cada hilo apunta cuando empieza y cuando acaba: si los intervalos no se
# cruzan, el camino concurrente no se ha ejercitado y la comprobacion se OMITE.
# Pasarla sin haberla ejercitado seria justo el falso positivo que se busca
# evitar (§ mismo criterio que `omite`).
INTEG = sql("""SELECT id FROM "Integration" WHERE "deletedAt" IS NULL
               AND "providerIdentifier"='instagram-standalone' LIMIT 1;""")
MARCA = "Suite de pruebas identidad externa"

def _crear(external_id, etiqueta, salida, barrera):
    cuerpo = {
        "type": "draft",  # borrador + fecha lejana: no puede publicar nada
        "shortLink": False, "tags": [],
        "date": (datetime.datetime.utcnow() + datetime.timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S"),
        "posts": [{
            "integration": {"id": INTEG},
            "settings": {"__type": "instagram-standalone", "post_type": "post"},
            "value": [{"content": "%s %s" % (MARCA, etiqueta), "image": []}],
        }],
    }
    if external_id:
        cuerpo["posts"][0]["externalId"] = external_id
    barrera.wait()  # las dos peticiones salen a la vez
    t0 = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            "https://postiz.dustincalderon.com/api/public/v1/posts",
            data=json.dumps(cuerpo).encode(),
            headers={"Authorization": APIK, "Content-Type": "application/json",
                     "User-Agent": "curl/8.5.0"}, method="POST"))
        res = json.loads(r.read())
    except Exception as e:
        res = {"error": str(e)[:200]}
    salida.append({"etiqueta": etiqueta, "t0": t0, "t1": time.time(), "res": res})

def _a_la_vez(external_id):
    salida = []; barrera = threading.Barrier(2)
    hilos = [threading.Thread(target=_crear, args=(external_id, e, salida, barrera))
             for e in ("A", "B")]
    for h in hilos: h.start()
    for h in hilos: h.join()
    return salida

def _solapan(s):
    if len(s) != 2: return False
    a, b = s
    return a["t0"] < b["t1"] and b["t0"] < a["t1"]

def _vivos_con(external_id):
    return sql("""SELECT count(*) FROM "Post" WHERE "deletedAt" IS NULL
                  AND "externalId"='%s';""" % external_id)

# --- Caso protegido: misma identidad externa, dos creaciones simultaneas.
EXT = "suite-" + uuid.uuid4().hex
prot = _a_la_vez(EXT)
if not _solapan(prot):
    omite("dos creaciones a la vez dejan un solo post",
          "las peticiones no llegaron a solaparse: no se ejercito el camino concurrente")
else:
    vivos = _vivos_con(EXT)
    check("dos creaciones a la vez dejan un solo post", vivos == "1", "(%s vivos)" % vivos)
    ids = {str((p["res"] or [{}])[0].get("postId")) for p in prot if isinstance(p["res"], list) and p["res"]}
    check("las dos peticiones devuelven el mismo post", len(ids) == 1, "(%s)" % ", ".join(sorted(ids)))
    reclamadas = sum(1 for p in prot if isinstance(p["res"], list) and p["res"]
                     and p["res"][0].get("alreadyClaimed"))
    # Exactamente una tiene que verse a si misma como "ya reclamada": la que
    # llego segunda. Si fueran cero, el servicio lanzaria dos workflows de
    # publicacion para el mismo post y el duplicado saltaria a Instagram.
    check("exactamente una se reconoce como ya reclamada", reclamadas == 1, "(%d)" % reclamadas)

# --- Grupo de control: sin identidad externa NO hay proteccion y deben salir
# dos. Si aqui saliera uno solo, el duplicado lo estaria evitando otra cosa y
# la comprobacion de arriba no probaria lo que dice probar.
ctrl = _a_la_vez(None)
n_ctrl = sql("""SELECT count(*) FROM "Post" WHERE "deletedAt" IS NULL
                AND "externalId" IS NULL AND content LIKE '%%%s%%';""" % MARCA)
check("el control sin identidad si crea dos (la proteccion es la que actua)",
      n_ctrl == "2", "(%s creados)" % n_ctrl)

# --- La retirada reclama por identidad, no solo por el id escrito en Notion.
# Rama anadida el 2026-08-24 y que HAY que ejercitar: un post recien creado
# cuya id aun no se escribio en Notion NO es un huerfano. Si no se reclamara,
# la retirada corriendo a la vez que el sync borraria un post legitimo y
# dejaria la fila apuntando a un id muerto -> no se publica nada, en silencio,
# que es peor que el duplicado visible.
def _post_directo(external_id, etiqueta, fecha_iso):
    cuerpo = {"type": "draft", "shortLink": False, "tags": [], "date": fecha_iso,
              "posts": [{"integration": {"id": INTEG},
                         "settings": {"__type": "instagram-standalone", "post_type": "post"},
                         "value": [{"content": "%s %s" % (MARCA, etiqueta), "image": []}],
                         "externalId": external_id}]}
    r = urllib.request.urlopen(urllib.request.Request(
        "https://postiz.dustincalderon.com/api/public/v1/posts",
        data=json.dumps(cuerpo).encode(),
        headers={"Authorization": APIK, "Content-Type": "application/json",
                 "User-Agent": "curl/8.5.0"}, method="POST"))
    return json.loads(r.read())[0]["postId"]

def _vivo(post_id):
    return sql('SELECT count(*) FROM "Post" WHERE id=\'%s\' AND "deletedAt" IS NULL;' % post_id) == "1"

_d9 = (datetime.date.today() + datetime.timedelta(days=9)).isoformat() + "T12:00:00.000+02:00"
_fila_ret = fila({"Status": {"select": {"name": "Listo"}}, "Fecha": {"date": {"start": _d9}}})
esperar_indice([_fila_ret])
_reclamado = _post_directo(_fila_ret, "reclamado por identidad", _d9)
# Control: misma forma, pero con una identidad que no corresponde a ninguna
# fila. Si la retirada no se lo llevara, seria que no llego a evaluar nada y el
# check de arriba estaria pasando sin haber probado nada.
_suelto = _post_directo("sin-fila-" + uuid.uuid4().hex, "sin fila detras", _d9)
hit(L + "postiz-retirada-ig", hdr={"X-Sync-Token": TOKEN})
check("la retirada NO borra un post reclamado por identidad", _vivo(_reclamado))
check("y si borra uno cuya identidad no tiene fila (control)", not _vivo(_suelto))
borrar(_fila_ret)

# --- Aprobada tarde: `modo` pasa a programar cuando la Fecha ya pasó. El post
# sigue siendo el borrador y el sync ignora una fila con post y fecha pasada: sin
# la recuperación, la fila se quedaría así para siempre sin decir nada.
_fila_tarde = fila({"Status": {"select": {"name": "En Postiz (borrador)"}}, "modo": {"select": {"name": "programar"}},
                    "Fecha": {"date": {"start": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)).isoformat()}}})
_hace2h = (datetime.datetime.utcnow() - datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
try:
    _borrador_tarde = _post_directo(_fila_tarde, "aprobada tarde", _hace2h)
except Exception as e:
    _borrador_tarde = None
    omite("aprobada tarde pasa a Error", "Postiz no dejó crear el borrador con fecha pasada: %s" % str(e)[:80])
if _borrador_tarde:
    api("https://api.notion.com/v1/pages/" + _fila_tarde,
        {"properties": {"❌ postiz_post_id": {"rich_text": [{"text": {"content": _borrador_tarde}}]}}}, m="PATCH")
    esperar_indice([_fila_tarde])
    hit(L + "postiz-retirada-ig", hdr={"X-Sync-Token": TOKEN})
    _rt = leer(_fila_tarde)
    check("aprobada tarde pasa a Error y dice por qué", _rt["Status"] == "Error" and "borrador" in _rt["error"],
          "(%s: %s)" % (_rt["Status"], _rt["error"][:60]))
borrar(_fila_tarde)

# --- Limpieza: por la API publica, el mismo borrado blando que la UI.
for pid in [l for l in sql("""SELECT id FROM "Post" WHERE "deletedAt" IS NULL
                              AND content LIKE '%%%s%%';""" % MARCA).split() if l]:
    try:
        urllib.request.urlopen(urllib.request.Request(
            "https://postiz.dustincalderon.com/api/public/v1/posts/" + pid,
            headers={"Authorization": APIK, "User-Agent": "curl/8.5.0"}, method="DELETE"))
    except Exception as e:
        print("  no se pudo borrar %s: %s" % (pid[:8], e))

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
