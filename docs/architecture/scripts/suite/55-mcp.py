# -*- coding: utf-8 -*-
# Parte de la batería: la ejecuta `suite-pruebas-postiz.py` en un espacio de nombres COMPARTIDO
# (lo que define una parte lo ven las siguientes). No se lanza suelta.
print(); print("=" * 62); print("6d · EL WEBHOOK DEL MCP DE REDES"); print("=" * 62)
# «Pipeline · MCP» (`POST /webhook/postiz-mcp`, cabecera `X-MCP-Token`) es lo único que el Worker
# `redes-mcp` puede llamar. Se prueba el webhook, no el Worker: sus tres operaciones y el rechazo.
# `reportar_averia` NO se prueba: encola una incidencia de verdad en el bus y despierta al triage
# del Beelink, que la trataría como un fallo real.
MCP_TOKEN = os.environ["N8N_MCP_TOKEN"]
MANUAL = "3b2a2405-a123-8002-8bba-deb342856945"   # «Manual de uso — Social Media»: Notion lo ve, el calendario no lo contiene

def mcp(cuerpo, token=MCP_TOKEN, espera=30):
    """Llama al webhook por local (sin Cloudflare: la espera de `sincronizar` pasa de lo que corta el túnel).
    Devuelve (status, cuerpo ya leído como JSON)."""
    h = {"Content-Type": "application/json", "User-Agent": "curl/8.5.0"}
    if token: h["X-MCP-Token"] = token
    try:
        r = urllib.request.urlopen(urllib.request.Request(L + "postiz-mcp", data=json.dumps(cuerpo).encode(), headers=h, method="POST"), timeout=espera)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        t = e.read().decode()
        try: return e.code, json.loads(t)
        except ValueError: return e.code, t

# --- 1 · quién entra: por la ruta pública, que es la que usa el Worker
c, b = hit(W + "postiz-mcp", '{"operacion":"salud"}')
check("MCP sin secreto rechaza", c == 403 and de_n8n(b), "(%d, %s)" % (c, "de n8n" if de_n8n(b) else "DE CLOUDFLARE — falta el bypass de Access de /webhook/postiz-mcp"))
c, b = hit(W + "postiz-mcp", '{"operacion":"salud"}', {"X-MCP-Token": "malo"})
check("MCP con secreto erróneo rechaza", c == 403 and de_n8n(b), "(%d)" % c)
c, b = hit(W + "postiz-mcp", '{"operacion":"salud"}', {"X-Sync-Token": TOKEN})
check("el secreto del sync NO abre el MCP (son secretos distintos)", c == 403 and de_n8n(b), "(%d)" % c)
c, b = mcp({"operacion": "salud"})
check("MCP con su secreto: salud", c == 200 and b == {"ok": True}, "(%d)" % c)

# --- 2 · lo que no es una operación o llega mal formado no toca nada
c, b = mcp({"operacion": "borrar"})
check("operación desconocida: 400", c == 400 and "error" in b, "(%d)" % c)
c, b = mcp({"operacion": "diagnosticar", "fila": "../../etc/passwd"})
check("diagnosticar con una fila mal formada: 400", c == 400, "(%d)" % c)
c, b = mcp({"operacion": "diagnosticar", "fila": MANUAL})
check("diagnosticar de una página que no es del calendario: 404, no la lee", c == 404 and "fila" not in b, "(%d)" % c)

# --- 3 · diagnosticar → sincronizar → diagnosticar, sobre una fila de prueba (`Por aprobar`: no puede publicar)
pid_mcp = fila({"Status": {"select": {"name": "Por aprobar"}}, "cuenta": {"select": {"name": "AMORISMO VOL III"}},
                "Fecha": {"date": {"start": d7 + "T20:00:00.000+02:00"}},
                "copy": {"rich_text": [{"text": {"content": "Suite de pruebas: mcp."}}]},
                "media": {"files": [{"type": "file_upload", "file_upload": {"id": subir("t1.jpg")}, "name": "t1.jpg"}]}})
esperar_indice([pid_mcp])
c, antes = mcp({"operacion": "diagnosticar", "fila": pid_mcp})
check("diagnosticar una fila sin post: sus hechos y ningún post", c == 200 and antes["fila"]["id"] == pid_mcp and antes["fila"]["estado"] == "Por aprobar"
      and antes["fila"]["postiz_post_id"] is None and antes["postiz"]["posts"] == [] and antes["fila"]["en_ventana_del_sync"] is True, "(%d)" % c)
c, s = mcp({"operacion": "sincronizar"}, espera=130)
check("sincronizar espera a que la pasada acabe", c == 200 and s == {"estado": "terminada"}, "(%d, %s)" % (c, s))
c, despues = mcp({"operacion": "diagnosticar", "fila": pid_mcp})
post_mcp = leer(pid_mcp)["post_id"]
posts_mcp = despues["postiz"]["posts"] if c == 200 else []
check("tras sincronizar, diagnosticar ve el borrador de Postiz, de la fila por identidad y por puntero",
      c == 200 and bool(post_mcp) and len(posts_mcp) == 1 and posts_mcp[0]["id"] == post_mcp and posts_mcp[0]["estado"] == "DRAFT"
      and sorted(posts_mcp[0]["coincide_por"]) == ["externalId", "postiz_post_id"] and despues["fila"]["postiz_post_id"] == post_mcp, "(%d)" % c)
