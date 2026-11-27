# -*- coding: utf-8 -*-
# Parte de la batería: la ejecuta `suite-pruebas-postiz.py` en un espacio de nombres COMPARTIDO
# (lo que define una parte lo ven las siguientes). No se lanza suelta.
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

# --- Limpieza: por la API publica, el mismo borrado blando que la UI.
for pid in [l for l in sql("""SELECT id FROM "Post" WHERE "deletedAt" IS NULL
                              AND content LIKE '%%%s%%';""" % MARCA).split() if l]:
    try:
        urllib.request.urlopen(urllib.request.Request(
            "https://postiz.dustincalderon.com/api/public/v1/posts/" + pid,
            headers={"Authorization": APIK, "User-Agent": "curl/8.5.0"}, method="DELETE"))
    except Exception as e:
        print("  no se pudo borrar %s: %s" % (pid[:8], e))

