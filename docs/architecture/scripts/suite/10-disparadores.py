# -*- coding: utf-8 -*-
# Parte de la batería: la ejecuta `suite-pruebas-postiz.py` en un espacio de nombres COMPARTIDO
# (lo que define una parte lo ven las siguientes). No se lanza suelta.
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

