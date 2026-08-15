# -*- coding: utf-8 -*-
"""Batería de pruebas del pipeline. No publica nada en Instagram."""
import json, urllib.request, os, uuid, subprocess, time, sys, datetime

TOK = os.environ["NOTION_API_KEY"]
TOKEN = os.environ["N8N_SYNC_IG_TOKEN"]
BTN = os.environ["N8N_SYNC_IG_BUTTON_PATH"]
RECV = os.environ["N8N_POSTIZ_WEBHOOK_PATH"]
DB = "186a2405a123812aa925cde1bb94ef12"
W = "https://auto.dustincalderon.com/webhook/"
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
    # dominio y devuelve 403 sin que la peticion llegue a n8n (§4.1). Sin esto
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

def borrar(pid):
    for b in ({"properties": {"Status": {"select": None}}}, {"archived": True}):
        api("https://api.notion.com/v1/pages/" + pid, b, m="PATCH")

print("=" * 62); print("1 · SEGURIDAD DE LOS DISPARADORES"); print("=" * 62)
c, b = hit(W + "postiz-sync-ig")
check("sync sin token rechaza", c == 403 and de_n8n(b), "(%d, %s)" % (c, "de n8n" if de_n8n(b) else "DE CLOUDFLARE — no llego a n8n"))
c, b = hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": "malo"})
check("sync con token erróneo rechaza", c == 403 and de_n8n(b), "(%d, %s)" % (c, "de n8n" if de_n8n(b) else "DE CLOUDFLARE — no llego a n8n"))
c, r = hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN}); check("sync con token correcto acepta", c == 200, "(%d)" % c)
c, _ = hit(W + "postiz-sync-0000000000000000"); check("ruta secreta errónea rechaza", c == 404, "(%d)" % c)
# 200 con "nada que hacer" (reposo) o con el JSON de una fila procesada:
# ambas son "el botón funciona". Exigir además el reposo mezclaba dos
# afirmaciones y fallaba en falso con filas reales en ventana (2026-08-15).
c, r = hit(W + BTN, '{"source":{"type":"automation"}}')
con_filas = '"object":"page"' in r
check("botón de Notion funciona", c == 200 and ("nada que hacer" in r or con_filas),
      "(%d%s)" % (c, ", con filas reales en ventana" if con_filas else ""))
c, _ = hit(W + RECV, "[]"); check("receptor acepta payload vacío", c == 200, "(%d)" % c)

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
hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
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
hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
r = leer(pid)
check("Status pasa a Programado", r["Status"] == "Programado")
check("escribe ❌ postiz_post_id", bool(r["post_id"]))
check("escribe ❌ postiz_media", r["media"].count("path") == 2, "(2 ficheros)")
check("❌ error_log queda vacío", not r["error"])
pid_post = r["post_id"]
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
hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
rm_ = leer(pid_m)
check("fila NUEVA dentro del margen SÍ se crea", rm_["Status"] == "En Postiz (borrador)" and bool(rm_["post_id"]),
      "(Status=%s)" % rm_["Status"])
if rm_["post_id"]:
    check("y es DRAFT, no publica", sql('SELECT state FROM "Post" WHERE id=\'%s\';' % rm_["post_id"]) == "DRAFT")
if rm_["post_id"]:
    # ...y una segunda pasada ya NO la toca, porque ahora sí tiene post_id
    hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
    r_m2 = leer(pid_m)
    check("y en la 2ª pasada ya no se recrea", r_m2["post_id"] == rm_["post_id"], "(mismo post_id)")
    check("sigue viva en Postiz", sql('SELECT "deletedAt" IS NULL FROM "Post" WHERE id=\'%s\';' % rm_["post_id"]) == "t")
api("https://api.notion.com/v1/pages/" + pid_m, {"properties": {"Status": {"select": None}}}, m="PATCH")
hit(W + "postiz-retirada-ig", hdr={"X-Sync-Token": TOKEN})
if rm_["post_id"]:
    vivo = sql('SELECT "deletedAt" IS NULL FROM "Post" WHERE id=\'%s\';' % rm_["post_id"])
    check("la retirada SÍ respeta el margen (no la borra)", vivo == "t", "(sigue viva, correcto)")
    sql('UPDATE "Post" SET "deletedAt"=now() WHERE id=\'%s\';' % rm_["post_id"])  # limpieza manual
api("https://api.notion.com/v1/pages/" + pid_m, {"archived": True}, m="PATCH")

print(); print("=" * 62); print("4 · REINTENTO REUTILIZA EL MEDIA"); print("=" * 62)
media_antes = r["media"]
t0 = time.time(); hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN}); dt = time.time() - t0
r2 = leer(pid)
check("no vuelve a subir los ficheros", r2["media"] == media_antes, "(%.1fs)" % dt)
check("crea un post nuevo", r2["post_id"] != pid_post)
check("borra el anterior", sql('SELECT "deletedAt" IS NOT NULL FROM "Post" WHERE id=\'%s\';' % pid_post) == "t")

print(); print("=" * 62); print("5 · RETIRADA"); print("=" * 62)
# Se comparan los posts WEB VIVOS antes y despues. La version anterior hacia
# SELECT sobre todos los WEB en QUEUE —hoy son 7, seis ya borrados— y comparaba
# las 7 lineas con "t", asi que no podia pasar nunca.
web_antes = sql('SELECT id FROM "Post" WHERE "creationMethod"=\'WEB\' AND state=\'QUEUE\' AND "deletedAt" IS NULL ORDER BY id;')
api("https://api.notion.com/v1/pages/" + pid, {"properties": {"Status": {"select": None}}}, m="PATCH")
hit(W + "postiz-retirada-ig", hdr={"X-Sync-Token": TOKEN})
check("retira el post huérfano", sql('SELECT "deletedAt" IS NOT NULL FROM "Post" WHERE id=\'%s\';' % r2["post_id"]) == "t")
web_despues = sql('SELECT id FROM "Post" WHERE "creationMethod"=\'WEB\' AND state=\'QUEUE\' AND "deletedAt" IS NULL ORDER BY id;')
check("NO toca los posts creados a mano (WEB)", web_antes == web_despues,
      "(%d vivos antes, %d después)" % (len(web_antes.split()), len(web_despues.split())))
api("https://api.notion.com/v1/pages/" + pid, {"archived": True}, m="PATCH")

print(); print("=" * 62); print("6 · ESTADO EN REPOSO"); print("=" * 62)
c, r1 = hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
if '"object":"page"' in r1:
    omite("sync no hace nada", "calendario con filas reales en ventana")
else:
    check("sync no hace nada", "nada que hacer" in r1)
c, r2 = hit(W + "postiz-retirada-ig", hdr={"X-Sync-Token": TOKEN})
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

print(); print("=" * 62); print("7 · LIMPIEZA"); print("=" * 62)
# La bateria sube ficheros de prueba y borra los posts, pero los Media quedaban
# vivos y habia que barrerlos a mano. Se borran por la API publica —el mismo
# soft-delete que la UI—, no por SQL, para no divergir del camino real.
APIK = sql('SELECT "apiKey" FROM "Organization" WHERE id=\'30c506a6-0a2c-4661-95bb-abec2e14b3f2\';')
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
