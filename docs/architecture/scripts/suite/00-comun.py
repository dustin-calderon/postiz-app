# -*- coding: utf-8 -*-
"""Lo común de la batería: entorno, ayudas, y el freno que borra lo que crea.

La batería NO puede garantizar por construcción que no publica nada: probar que `Listo`
crea un `schedule` exige crear uno de verdad en un canal real. Lo que sí garantiza es que
no queda nada vivo, aunque muera a medias: toda fila que crea se registra en FILAS y
`limpiar_todo` (al salir, con SIGTERM/SIGHUP y al arrancar la siguiente) vacía su Status,
borra su post por la API de Postiz y la archiva. Los `schedule` van a 7 días como mínimo.
"""
import json, urllib.request, os, re, uuid, subprocess, time, sys, datetime, threading, atexit, signal

TOK = os.environ["NOTION_API_KEY"]
TOKEN = os.environ["N8N_SYNC_IG_TOKEN"]
BTN = os.environ["N8N_SYNC_IG_BUTTON_PATH"]
RECV = os.environ["N8N_POSTIZ_WEBHOOK_PATH"]
DS = "186a2405-a123-81dc-832f-000b82a65c0c"  # la fuente de datos del calendario (Notion-Version 2025-09-03)
W = "https://auto.dustincalderon.com/webhook/"
# Lo que espera a que acabe una pasada va a n8n desde el propio Beelink, sin
# Cloudflare: Cloudflare corta a los 125 s una respuesta que no llega (524), y una
# pasada con bastantes filas, o que espera turno, los pasa; se leería el
# resultado antes de tiempo. Por W solo va lo que prueba el camino público.
L = "http://127.0.0.1:5678/webhook/"
H = {"Authorization": "Bearer " + TOK, "Notion-Version": "2025-09-03"}
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

FILAS = []   # toda fila que crea la suite: la limpieza las recorre

def fila(props):
    base = {"Name": {"title": [{"text": {"content": "__ZZ suite (borrar)"}}]},
            "Plataforma": {"multi_select": [{"name": "Instagram"}]}}
    base.update(props)
    nueva = api("https://api.notion.com/v1/pages", {"parent": {"type": "data_source_id", "data_source_id": DS}, "properties": base})["id"]
    FILAS.append(nueva)
    return nueva

def esperar_indice(pids, intentos=12):
    """El indice de consulta de Notion va por detras de la escritura: una fila
    recien creada tarda unos segundos en aparecer en /data_sources/{id}/query.
    Sin esta espera el sync no las ve y la suite falla por un motivo falso."""
    q = {"page_size": 100, "filter": {"property": "Name", "title": {"contains": "__ZZ suite"}}}
    for i in range(intentos):
        vistos = {r["id"] for r in api("https://api.notion.com/v1/data_sources/%s/query" % DS, q, m="POST")["results"]}
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
    for b in ({"properties": {"Status": {"select": None}}}, {"in_trash": True}):
        api("https://api.notion.com/v1/pages/" + pid, b, m="PATCH")

# Clave de la API publica de Postiz. Vive aqui y no en la seccion de limpieza
# porque la 6b tambien crea posts por la API.
APIK = sql('SELECT "apiKey" FROM "Organization" WHERE id=\'30c506a6-0a2c-4661-95bb-abec2e14b3f2\';')

INTEG = sql("""SELECT id FROM "Integration" WHERE "deletedAt" IS NULL
               AND "providerIdentifier"='instagram-standalone' LIMIT 1;""")
MARCA = "Suite de pruebas identidad externa"

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


def borrar_post(post_id):
    try:
        urllib.request.urlopen(urllib.request.Request(
            "https://postiz.dustincalderon.com/api/public/v1/posts/" + post_id,
            headers={"Authorization": APIK, "User-Agent": "curl/8.5.0"}, method="DELETE"))
    except Exception as e:
        print("  no se pudo borrar el post %s: %s" % (post_id[:8], e))

def limpiar_fila(pid):
    """Vacía su Status (deja de reclamar), borra su post y la archiva. Idempotente."""
    try:
        post_id = leer(pid)["post_id"]
        api("https://api.notion.com/v1/pages/" + pid, {"properties": {"Status": {"select": None}}}, m="PATCH")
        if post_id:
            borrar_post(post_id)
        api("https://api.notion.com/v1/pages/" + pid, {"in_trash": True}, m="PATCH")
    except Exception as e:
        print("  no se pudo limpiar la fila %s: %s" % (pid[:8], str(e)[:80]))

def limpiar_todo():
    for pid in reversed(FILAS):
        limpiar_fila(pid)
    for post_id in [l for l in sql("""SELECT id FROM "Post" WHERE "deletedAt" IS NULL
                                      AND content LIKE '%Suite de pruebas%';""").split() if l]:
        borrar_post(post_id)

atexit.register(limpiar_todo)
for _senal in (signal.SIGTERM, signal.SIGHUP):
    signal.signal(_senal, lambda n, f: sys.exit(128 + n))   # sys.exit sí ejecuta atexit

def barrido_previo():
    """Lo que dejó una suite anterior que murió sin limpiar: filas suyas y sus posts."""
    q = {"page_size": 100, "filter": {"property": "Name", "title": {"contains": "__ZZ suite"}}}
    viejas = [r["id"] for r in api("https://api.notion.com/v1/data_sources/%s/query" % DS, q, m="POST")["results"]]
    for pid in viejas:
        limpiar_fila(pid)
    print("barrido previo: %d filas de una suite anterior" % len(viejas))
    limpiar_todo()

def esperar_estado(pid, estado, intentos=12):
    """El índice de consulta de Notion va por detrás de la escritura: un cambio de
    `Status` tarda unos segundos en verse en la consulta que hace el sync."""
    q = {"page_size": 100, "filter": {"and": [{"property": "Name", "title": {"contains": "__ZZ suite"}},
                                              {"property": "Status", "select": {"equals": estado}}]}}
    for _ in range(intentos):
        if any(x["id"] == pid for x in api("https://api.notion.com/v1/data_sources/%s/query" % DS, q, m="POST")["results"]):
            return True
        time.sleep(2)
    return False

def esperar_fecha_lejana(pid, intentos=12):
    """Lo mismo para una `Fecha` movida a más de 20 días."""
    q = {"page_size": 10, "filter": {"property": "Fecha", "date": {"after": (datetime.date.today() + datetime.timedelta(days=20)).isoformat()}}}
    for _ in range(intentos):
        if any(x["id"] == pid for x in api("https://api.notion.com/v1/data_sources/%s/query" % DS, q, m="POST")["results"]):
            return True
        time.sleep(2)
    return False

def estado_post(post_id):
    return sql('SELECT state FROM "Post" WHERE id=\'%s\';' % post_id)

barrido_previo()
