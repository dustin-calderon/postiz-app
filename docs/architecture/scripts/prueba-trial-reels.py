# -*- coding: utf-8 -*-
"""Prueba de trial reels. modo=borrador SIEMPRE: nada puede salir a Instagram."""
import json, urllib.request, os, uuid, subprocess, time, sys, datetime

TOK = os.environ["NOTION_API_KEY"]
TOKEN = os.environ["N8N_SYNC_IG_TOKEN"]
DB = "186a2405a123812aa925cde1bb94ef12"
W = "https://auto.dustincalderon.com/webhook/"
H = {"Authorization": "Bearer " + TOK, "Notion-Version": "2022-06-28"}
ok, fail = [], []


def api(u, d=None, m=None, h=None, raw=False):
    hh = dict(H)
    if h:
        hh.update(h)
    if d is not None and not raw:
        d = json.dumps(d).encode()
        hh["Content-Type"] = "application/json"
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(u, data=d, headers=hh, method=m), timeout=120).read())


def hit(url, body="{}", hdr=None):
    h = {"Content-Type": "application/json", "User-Agent": "curl/8.5.0"}
    if hdr:
        h.update(hdr)
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, data=body.encode(), headers=h, method="POST"), timeout=300)
        return r.status, r.read().decode()[:160]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:160]


def sql(q):
    return subprocess.check_output(
        ["docker", "exec", "postiz-postgres", "psql", "-U", "postiz", "-d", "postiz_db", "-tAc", q]).decode().strip()


def check(nombre, cond, det=""):
    (ok if cond else fail).append(nombre)
    print("  %s %s %s" % ("PASA " if cond else "FALLA", nombre, det))


def subir(fichero, tipo):
    fu = api("https://api.notion.com/v1/file_uploads", {"filename": fichero, "content_type": tipo})
    b = "----" + uuid.uuid4().hex
    body = open("/tmp/" + fichero, "rb").read()
    parts = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
             % (b, fichero, tipo)).encode() + body + ("\r\n--%s--\r\n" % b).encode()
    api(fu["upload_url"], parts, h={"Content-Type": "multipart/form-data; boundary=" + b}, raw=True)
    return fu["id"]


def fila(props):
    base = {"Name": {"title": [{"text": {"content": "__ZZ trial (borrar)"}}]},
            "Plataforma": {"multi_select": [{"name": "Instagram"}]},
            "modo": {"select": {"name": "borrador"}}}   # nunca publica
    base.update(props)
    return api("https://api.notion.com/v1/pages", {"parent": {"database_id": DB}, "properties": base})["id"]


def leer(pid):
    p = api("https://api.notion.com/v1/pages/" + pid)["properties"]
    t = lambda k: "".join(x["plain_text"] for x in p[k]["rich_text"])
    return {"Status": (p["Status"].get("select") or {}).get("name"),
            "post_id": t("❌ postiz_post_id"), "error": t("❌ error_log")}


def esperar_indice(pids, intentos=12):
    q = {"page_size": 100, "filter": {"property": "Name", "title": {"contains": "__ZZ trial"}}}
    for i in range(intentos):
        vistos = {r["id"] for r in api("https://api.notion.com/v1/databases/%s/query" % DB, q, m="POST")["results"]}
        if all(p in vistos for p in pids):
            return True
        time.sleep(2)
    print("  AVISO: el indice de Notion no reflejo las filas")
    return False


F = (datetime.date.today() + datetime.timedelta(days=7)).isoformat() + "T17:00:00.000+02:00"
print("=" * 66); print("PREPARACION: un video y una imagen de prueba"); print("=" * 66)
subprocess.run("ffmpeg -y -f lavfi -i testsrc=size=720x1280:rate=25 -t 3 -pix_fmt yuv420p /tmp/v1.mp4",
               shell=True, capture_output=True)
subprocess.run("ffmpeg -y -f lavfi -i testsrc=size=1080x1080:rate=1 -frames:v 1 /tmp/i1.jpg",
               shell=True, capture_output=True)
print("  video: %d B · imagen: %d B" % (os.path.getsize("/tmp/v1.mp4"), os.path.getsize("/tmp/i1.jpg")))
vid1, vid2, img1 = subir("v1.mp4", "video/mp4"), subir("v1.mp4", "video/mp4"), subir("i1.jpg", "image/jpeg")

M = lambda i, n: {"files": [{"type": "file_upload", "file_upload": {"id": i}, "name": n}]}
BASE = {"Status": {"select": {"name": "Listo"}}, "cuenta": {"select": {"name": "AMORISMO VOL III"}},
        "Fecha": {"date": {"start": F}}, "copy": {"rich_text": [{"text": {"content": "Prueba trial."}}]}}

print(); print("=" * 66); print("1 · LO QUE DEBE FALLAR, CON MOTIVO LEGIBLE"); print("=" * 66)
malos = [
 ("trial + imagen",  {**BASE, "Tipo": {"select": {"name": "Reel"}},
                      "is_trial_reel": {"checkbox": True}, "media": M(img1, "i1.jpg")}, "video"),
 ("trial + 2 ficheros", {**BASE, "Tipo": {"select": {"name": "Reel"}}, "is_trial_reel": {"checkbox": True},
                      "media": {"files": [{"type": "file_upload", "file_upload": {"id": vid1}, "name": "v1.mp4"},
                                          {"type": "file_upload", "file_upload": {"id": vid2}, "name": "v2.mp4"}]}}, "1 fichero"),
 ("trial + Historia", {**BASE, "Tipo": {"select": {"name": "Historia"}},
                      "is_trial_reel": {"checkbox": True}, "media": M(vid1, "v1.mp4")}, "Historia"),
]
pids = [fila(p) for _n, p, _e in malos]
esperar_indice(pids)
hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
for (nombre, _p, esperado), pid in zip(malos, pids):
    r = leer(pid)
    check(nombre + " -> Error", r["Status"] == "Error", "motivo: " + r["error"][:70])
    check(nombre + " -> el motivo lo explica", esperado in r["error"], "(esperaba %r)" % esperado)
for pid in pids:
    api("https://api.notion.com/v1/pages/" + pid, {"properties": {"Status": {"select": None}}}, m="PATCH")
    api("https://api.notion.com/v1/pages/" + pid, {"archived": True}, m="PATCH")

print(); print("=" * 66); print("2 · EL CAMINO BUENO: 1 video + trial"); print("=" * 66)
vid3 = subir("v1.mp4", "video/mp4")
pid = fila({**BASE, "Tipo": {"select": {"name": "Reel"}},
            "is_trial_reel": {"checkbox": True}, "media": M(vid3, "v1.mp4")})
esperar_indice([pid])
hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
r = leer(pid)
check("se crea (como borrador)", r["Status"] == "En Postiz (borrador)" and bool(r["post_id"]),
      "(Status=%s · %s)" % (r["Status"], r["error"][:60]))
if r["post_id"]:
    st = sql("SELECT state FROM \"Post\" WHERE id='%s';" % r["post_id"])
    check("es DRAFT, no publica", st == "DRAFT", "(%s)" % st)
    s = sql("SELECT settings FROM \"Post\" WHERE id='%s';" % r["post_id"])
    print("  settings guardados: %s" % s[:220])
    try:
        js = json.loads(s)
    except ValueError:
        js = {}
    check("settings.is_trial_reel = true", js.get("is_trial_reel") is True, "(%r)" % js.get("is_trial_reel"))
    check("no se cuela graduation_strategy", "graduation_strategy" not in js)
    sql("UPDATE \"Post\" SET \"deletedAt\"=now() WHERE id='%s';" % r["post_id"])
api("https://api.notion.com/v1/pages/" + pid, {"properties": {"Status": {"select": None}}}, m="PATCH")
api("https://api.notion.com/v1/pages/" + pid, {"archived": True}, m="PATCH")

print(); print("=" * 66); print("3 · SIN MARCAR, NADA CAMBIA"); print("=" * 66)
vid4 = subir("v1.mp4", "video/mp4")
pid2 = fila({**BASE, "Tipo": {"select": {"name": "Reel"}}, "media": M(vid4, "v1.mp4")})
esperar_indice([pid2])
hit(W + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
r2 = leer(pid2)
check("un reel normal sigue creandose", bool(r2["post_id"]), "(Status=%s · %s)" % (r2["Status"], r2["error"][:50]))
if r2["post_id"]:
    s2 = sql("SELECT settings FROM \"Post\" WHERE id='%s';" % r2["post_id"])
    check("NO lleva is_trial_reel", "is_trial_reel" not in s2, "(%s)" % s2[:120])
    sql("UPDATE \"Post\" SET \"deletedAt\"=now() WHERE id='%s';" % r2["post_id"])
api("https://api.notion.com/v1/pages/" + pid2, {"properties": {"Status": {"select": None}}}, m="PATCH")
api("https://api.notion.com/v1/pages/" + pid2, {"archived": True}, m="PATCH")

print(); print("=" * 66)
print("RESULTADO: %d pasan, %d fallan" % (len(ok), len(fail)))
if fail:
    print("FALLAN: " + ", ".join(fail)); sys.exit(1)
print("TODO CORRECTO")
