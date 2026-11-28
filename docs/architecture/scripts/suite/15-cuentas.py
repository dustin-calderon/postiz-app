# -*- coding: utf-8 -*-
# Parte de la batería: la ejecuta `suite-pruebas-postiz.py` en un espacio de nombres COMPARTIDO
# (lo que define una parte lo ven las siguientes). No se lanza suelta.
print(); print("=" * 62); print("2b · CADA CUENTA DEL CALENDARIO PUBLICA POR SU INTEGRACIÓN"); print("=" * 62)
# Las demás partes usan un solo canal de prueba. Aquí se recorren TODAS las
# opciones de `cuenta`: añadir una en Notion sin darla de alta en `Planificar`
# (o sin integración sana en Postiz), o que una integración caduque, tiene que
# saltar en la batería y no en una publicación real. Todo va en `Por aprobar`
# (borrador): ninguna de estas filas puede publicar. Están en FILAS, así que
# `limpiar_todo` las barre aunque la suite muera; además se limpian al acabar
# para que las partes siguientes no las encuentren en la ventana del sync.
from zoneinfo import ZoneInfo

opciones = [o["name"] for o in api("https://api.notion.com/v1/data_sources/" + DS)["properties"]["cuenta"]["select"]["options"]]
check("el calendario de Notion tiene cuentas", bool(opciones), "(%d opciones)" % len(opciones))

# El mapa que EJECUTA n8n: el de la versión publicada (activeVersionId), no el de
# la última guardada ni el de la documentación. Es lo que decide a qué integración
# va cada fila. Si no se puede leer, falla un check y la batería sigue.
try:
    _nodos = json.loads(n8n_sql("""SELECT h.nodes FROM workflow_history h JOIN workflow_entity w
        ON h."versionId" = w."activeVersionId" WHERE w.id = 'eKxZPM4zjwhNb3vf';"""))
    _js = next((n["parameters"]["jsCode"] for n in _nodos if n["name"] == "Planificar"), "")
except Exception as _e:
    _js = ""
    print("  no se pudo leer la versión publicada del sync: %s" % str(_e)[:80])
_m = re.search(r"const ACCOUNTS\s*=\s*\{(.*?)\}\s*;", _js, re.S)
ACCOUNTS = dict(re.findall(r"""['"]([^'"]+)['"]\s*:\s*['"]([^'"]+)['"]""", _m.group(1))) if _m else {}
check("se lee ACCOUNTS de la versión publicada de Planificar", bool(ACCOUNTS), "(%d cuentas)" % len(ACCOUNTS))

sobran = sorted(set(ACCOUNTS) - set(opciones))
check("ACCOUNTS no tiene cuentas que no sean opción de Notion", not sobran, "(%s)" % ", ".join(sobran) if sobran else "")
# Pegar una línea nueva copiando otra deja dos cuentas en la misma integración, y
# «sale por SU integración» lo daría por bueno: compara contra el propio mapa.
check("ACCOUNTS no repite integración", len(set(ACCOUNTS.values())) == len(ACCOUNTS))

# El archivador de Drive lleva su propia copia del mapa (NOTION_SCHEMA §2.1, paso 5):
# se compara con la copia VIVA, la que ejecuta el cron.
try:
    _arch = open("/opt/homeserver/scripts/archivo_drive_cuentas.py", encoding="utf-8").read()
    _cm = re.search(r"CUENTAS\s*=\s*\{(.*?)\n\}", _arch, re.S)
    CUENTAS_DRIVE = dict(re.findall(r'"([\w-]+)"\s*:\s*"([^"]+)"', _cm.group(1))) if _cm else {}
except OSError as _e:
    CUENTAS_DRIVE = {}
    print("  no se pudo leer el archivador de Drive: %s" % _e)
_desfase = sorted(c for c, i in ACCOUNTS.items() if CUENTAS_DRIVE.get(i) != c)
check("el archivador de Drive tiene cada cuenta con su mismo nombre", bool(CUENTAS_DRIVE) and not _desfase,
      "(%s)" % ", ".join(_desfase) if _desfase else "")

# Una cuenta solo se prueba de punta a punta si pasa lo anterior: probarla rota
# fallaría por un motivo que ya se ha dicho arriba.
probables = []
for _cuenta in opciones:
    _id = ACCOUNTS.get(_cuenta)
    if not _id:
        check("%s está en ACCOUNTS" % _cuenta, False)
        omite("%s de punta a punta" % _cuenta, "no está en ACCOUNTS")
        continue
    check("%s está en ACCOUNTS" % _cuenta, True)
    # El id sale de un literal de n8n: solo se interpola si es un id y nada más.
    sana = bool(re.fullmatch(r"[\w-]+", _id)) and sql("""SELECT count(*) FROM "Integration" WHERE id='%s'
        AND "deletedAt" IS NULL AND disabled=false AND "refreshNeeded"=false AND "inBetweenSteps"=false
        AND "providerIdentifier"='instagram-standalone'
        AND "organizationId"='30c506a6-0a2c-4661-95bb-abec2e14b3f2';""" % _id) == "1"
    check("%s: su integración existe, está activa y es instagram-standalone" % _cuenta, sana, "(%s)" % _id[:8])
    if sana:
        probables.append(_cuenta)
    else:
        omite("%s de punta a punta" % _cuenta, "su integración no está sana")

if probables:
    subprocess.run("ffmpeg -y -f lavfi -i testsrc=size=1080x1080:rate=1 -t 1 -frames:v 1 /tmp/cuenta.jpg", shell=True, capture_output=True)
    # Madrid con su offset de HOY +7 días (verano +02:00, invierno +01:00): fijarlo
    # a mano desplaza la hora en la mitad del año.
    _fecha = (datetime.datetime.now(ZoneInfo("Europe/Madrid")) + datetime.timedelta(days=7)).replace(hour=18, minute=0, second=0, microsecond=0).isoformat()
    de_cuenta = {}
    for _cuenta in probables:
        _pid = fila({"Status": {"select": {"name": "Por aprobar"}}, "cuenta": {"select": {"name": _cuenta}},
                     "Tipo": {"select": {"name": "Post"}},
                     "Fecha": {"date": {"start": _fecha}},
                     "copy": {"rich_text": [{"text": {"content": "Suite de pruebas: cuenta %s." % _cuenta}}]},
                     "media": {"files": [{"type": "file_upload", "file_upload": {"id": subir("cuenta.jpg")}, "name": "cuenta.jpg"}]}})
        de_cuenta[_pid] = _cuenta
    esperar_indice(list(de_cuenta))
    hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})   # UNA sola pasada para todas
    for _pid, _cuenta in de_cuenta.items():
        _r = leer(_pid)
        # ❌ postiz_post_id es editable en Notion: solo se lleva al SQL si es un id.
        _post = _r["post_id"] if re.fullmatch(r"[\w-]+", _r["post_id"] or "") else ""
        check("%s: escribe ❌ postiz_post_id" % _cuenta, bool(_post))
        check("%s: el post es un borrador vivo en Postiz y la fila sigue en Por aprobar" % _cuenta,
              bool(_post) and _vivo(_post) and estado_post(_post) == "DRAFT" and _r["Status"] == "Por aprobar", "(%s)" % _r["Status"])
        _integ = sql('SELECT "integrationId" FROM "Post" WHERE id=\'%s\';' % _post) if _post else ""
        check("%s: el post sale por SU integración" % _cuenta, _integ == ACCOUNTS[_cuenta], "(%s)" % (_integ[:8] or "sin post"))
        check("%s: ❌ error_log queda vacío" % _cuenta, not _r["error"], _r["error"][:80])
        limpiar_fila(_pid)
