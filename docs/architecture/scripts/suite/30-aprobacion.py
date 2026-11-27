# -*- coding: utf-8 -*-
# Parte de la batería: la ejecuta `suite-pruebas-postiz.py` en un espacio de nombres COMPARTIDO
# (lo que define una parte lo ven las siguientes). No se lanza suelta.
print(); print("=" * 62); print("3b · EL MARGEN NO SE COME LAS FILAS NUEVAS"); print("=" * 62)
# Regresion: el margen (5 min desde el 2026-08-15; antes 2 h) protege el
# borrar-y-recrear. Aplicado tambien a filas nuevas, una aprobada para dentro
# del margen se salta en cada pasada —la fecha solo se acerca— y no se crea
# nunca. La fila va a +4 min para caer DENTRO del margen actual.
# Status=Por aprobar a proposito: la fecha cae en minutos y un QUEUE saldria
# publicado de verdad a Instagram si la limpieza fallara. El margen se evalua
# en `Planificar`, antes de que el estado decida el `type`, asi que la regresion
# se prueba igual con riesgo cero.
dentro = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=4))
f3 = subir("t1.jpg")
pid_m = fila({"Status": {"select": {"name": "Por aprobar"}}, "cuenta": {"select": {"name": "AMORISMO VOL III"}},
              "Fecha": {"date": {"start": dentro.isoformat()}},
              "copy": {"rich_text": [{"text": {"content": "Dentro del margen."}}]},
              "media": {"files": [{"type": "file_upload", "file_upload": {"id": f3}, "name": "t1.jpg"}]}})
esperar_indice([pid_m])
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
rm_ = leer(pid_m)
check("fila NUEVA dentro del margen SÍ se crea, y sigue en Por aprobar", rm_["Status"] == "Por aprobar" and bool(rm_["post_id"]),
      "(Status=%s)" % rm_["Status"])
if rm_["post_id"]:
    check("y es DRAFT, no publica", sql('SELECT state FROM "Post" WHERE id=\'%s\';' % rm_["post_id"]) == "DRAFT")
if rm_["post_id"]:
    # ...y una segunda pasada ya NO la toca, porque ahora sí tiene post_id
    hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
    r_m2 = leer(pid_m)
    check("y en la 2ª pasada ya no se recrea, ni se aprueba sola", r_m2["post_id"] == rm_["post_id"] and r_m2["Status"] == "Por aprobar", "(mismo post_id)")
    check("sigue viva en Postiz", sql('SELECT "deletedAt" IS NULL FROM "Post" WHERE id=\'%s\';' % rm_["post_id"]) == "t")
api("https://api.notion.com/v1/pages/" + pid_m, {"properties": {"Status": {"select": None}}}, m="PATCH")
hit(L + "postiz-retirada-ig", hdr={"X-Sync-Token": TOKEN})
if rm_["post_id"]:
    vivo = sql('SELECT "deletedAt" IS NULL FROM "Post" WHERE id=\'%s\';' % rm_["post_id"])
    check("la retirada SÍ respeta el margen (no la borra)", vivo == "t", "(sigue viva, correcto)")
    sql('UPDATE "Post" SET "deletedAt"=now() WHERE id=\'%s\';' % rm_["post_id"])  # limpieza manual
api("https://api.notion.com/v1/pages/" + pid_m, {"in_trash": True}, m="PATCH")

print(); print("=" * 62); print("5b · APLAZAR MÁS DE 15 DÍAS RETIRA EL POST"); print("=" * 62)
# Una pieza ya en Postiz cuya Fecha pasa a más de 15 días: el sync no la toca
# hasta que la nueva fecha entre en la ventana, así que su post es el de la
# fecha vieja y, si la fila lo reclamara, saldría igual. Borrador (`Por aprobar`)
# a propósito: no puede publicar nada. La retirada no escribe `Listo` sobre ella.
d30 = (datetime.date.today() + datetime.timedelta(days=30)).isoformat() + "T20:00:00.000+02:00"
pid_a = fila({"Status": {"select": {"name": "Por aprobar"}}, "cuenta": {"select": {"name": "AMORISMO VOL III"}},
              "Fecha": {"date": {"start": d7 + "T20:00:00.000+02:00"}},
              "copy": {"rich_text": [{"text": {"content": "Suite de pruebas: aplazada."}}]},
              "media": {"files": [{"type": "file_upload", "file_upload": {"id": subir("t1.jpg")}, "name": "t1.jpg"}]}})
esperar_indice([pid_a])
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
ra = leer(pid_a)
check("la pieza está en Postiz antes de aplazarla, sigue en Por aprobar", ra["Status"] == "Por aprobar" and bool(ra["post_id"]), "(%s)" % ra["Status"])
api("https://api.notion.com/v1/pages/" + pid_a, {"properties": {"Fecha": {"date": {"start": d30}}}}, m="PATCH")
esperar_fecha_lejana(pid_a)
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})  # el sync lanza la retirada
if ra["post_id"]:
    check("aplazarla retira el post de la fecha vieja", sql('SELECT "deletedAt" IS NOT NULL FROM "Post" WHERE id=\'%s\';' % ra["post_id"]) == "t")
st_a = leer(pid_a)["Status"]
check("y la fila conserva Por aprobar (la retirada no aprueba)", st_a == "Por aprobar", "(%s)" % st_a)
borrar(pid_a)

print(); print("=" * 62); print("5c · APROBAR: Por aprobar → Listo CREA EL SCHEDULE"); print("=" * 62)
# El gesto central del pipeline. Crea un `schedule` REAL en AMORISMO VOL III a 7
# días —no hay otra forma de probar que `Listo` publica—, así que la fila está en
# FILAS: `limpiar_todo` borra su post al salir, con SIGTERM/SIGHUP y al arrancar la
# suite siguiente, aunque esta muera a medias.
pid_g = fila({"Status": {"select": {"name": "Por aprobar"}}, "cuenta": {"select": {"name": "AMORISMO VOL III"}},
              "Fecha": {"date": {"start": d7 + "T21:00:00.000+02:00"}},
              "copy": {"rich_text": [{"text": {"content": "Suite de pruebas: aprobar."}}]},
              "media": {"files": [{"type": "file_upload", "file_upload": {"id": subir("t1.jpg")}, "name": "t1.jpg"}]}})
esperar_indice([pid_g])
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
rg = leer(pid_g)
borrador = rg["post_id"]
check("Por aprobar: el borrador está en Postiz (DRAFT) y la fila no cambia",
      rg["Status"] == "Por aprobar" and bool(borrador) and estado_post(borrador) == "DRAFT", "(%s)" % rg["Status"])
api("https://api.notion.com/v1/pages/" + pid_g, {"properties": {"Status": {"select": {"name": "Listo"}}}}, m="PATCH")
esperar_estado(pid_g, "Listo")
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
rg2 = leer(pid_g)
check("Listo: el post se recrea como schedule (QUEUE) y la fila pasa a Programado",
      bool(rg2["post_id"]) and rg2["post_id"] != borrador and estado_post(rg2["post_id"]) == "QUEUE" and rg2["Status"] == "Programado",
      "(%s)" % rg2["Status"])
if borrador:
    check("y el borrador anterior se borra", sql('SELECT "deletedAt" IS NOT NULL FROM "Post" WHERE id=\'%s\';' % borrador) == "t")
# Una `Programado` aplazada a más de 15 días vuelve a `Listo` (sigue aprobada) y su post se retira.
api("https://api.notion.com/v1/pages/" + pid_g, {"properties": {"Fecha": {"date": {"start": d30}}}}, m="PATCH")
esperar_fecha_lejana(pid_g)
hit(L + "postiz-sync-ig", hdr={"X-Sync-Token": TOKEN})
if rg2["post_id"]:
    check("aplazarla retira el schedule de la fecha vieja", sql('SELECT "deletedAt" IS NOT NULL FROM "Post" WHERE id=\'%s\';' % rg2["post_id"]) == "t")
st_g = leer(pid_g)["Status"]
check("y la Programado aplazada vuelve a Listo", st_g == "Listo", "(%s)" % st_g)
limpiar_fila(pid_g)

# --- Aprobada tarde: la fila pasa a `Listo` cuando la Fecha ya pasó. El post
# sigue siendo el borrador y el sync ignora una fila con post y fecha pasada: sin
# la recuperación, la fila se quedaría así para siempre sin decir nada. La misma
# situación en `Por aprobar` no se juzga: un borrador no se publica.
_hace2h = (datetime.datetime.utcnow() - datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
for _estado in ("Listo", "Por aprobar"):
    _fila_tarde = fila({"Status": {"select": {"name": _estado}},
                        "Fecha": {"date": {"start": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)).isoformat()}}})
    try:
        _borrador_tarde = _post_directo(_fila_tarde, "aprobada tarde " + _estado, _hace2h)
    except Exception as e:
        _borrador_tarde = None
        omite("%s con la Fecha pasada y el post en DRAFT" % _estado, "Postiz no dejó crear el borrador con fecha pasada: %s" % str(e)[:80])
    if _borrador_tarde:
        api("https://api.notion.com/v1/pages/" + _fila_tarde,
            {"properties": {"❌ postiz_post_id": {"rich_text": [{"text": {"content": _borrador_tarde}}]}}}, m="PATCH")
        esperar_indice([_fila_tarde])
        hit(L + "postiz-retirada-ig", hdr={"X-Sync-Token": TOKEN})
        _rt = leer(_fila_tarde)
        if _estado == "Listo":
            check("aprobada tarde (Listo) pasa a Error y dice por qué", _rt["Status"] == "Error" and "borrador" in _rt["error"],
                  "(%s: %s)" % (_rt["Status"], _rt["error"][:60]))
        else:
            check("Por aprobar con la Fecha pasada no se juzga: sigue igual y sin error",
                  _rt["Status"] == "Por aprobar" and not _rt["error"], "(%s: %s)" % (_rt["Status"], _rt["error"][:60]))
    borrar(_fila_tarde)

