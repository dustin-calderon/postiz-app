# -*- coding: utf-8 -*-
# Parte de la batería: la ejecuta `suite-pruebas-postiz.py` en un espacio de nombres COMPARTIDO
# (lo que define una parte lo ven las siguientes). No se lanza suelta.
print(); print("=" * 62); print("6d · EL WEBHOOK DEL MCP DE REDES"); print("=" * 62)
# «Pipeline · MCP» (`POST /webhook/postiz-mcp`, cabecera `X-MCP-Token`) es lo único que el Worker
# `redes-mcp` puede llamar para lo que solo existe en el Beelink (Postiz, el sync, el bus). Se prueba el
# webhook, no el Worker: sus operaciones y el rechazo. El calendario ya no pasa por aquí: lo lee y escribe el
# Worker con su propio token de Notion, y eso se prueba en su suite (`servers/redes-mcp`).
# `reportar_averia` NO se prueba: encola una incidencia de verdad en el bus y despierta al triage
# del Beelink, que la trataría como un fallo real.
MCP_TOKEN = os.environ["N8N_MCP_TOKEN"]

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
c, b = mcp({"operacion": "postiz", "fila": "../../etc/passwd"})
check("postiz con una fila mal formada: 400", c == 400, "(%d)" % c)
c, b = mcp({"operacion": "postiz", "fila": "3b2a2405-a123-8100-8000-000000000001", "puntero": "../x"})
check("postiz con un puntero mal formado: 400", c == 400, "(%d)" % c)

# --- 3 · postiz → sincronizar → postiz, sobre una fila de prueba (`Por aprobar`: no puede publicar)
pid_mcp = fila({"Status": {"select": {"name": "Por aprobar"}}, "cuenta": {"select": {"name": "AMORISMO VOL III"}},
                "Fecha": {"date": {"start": d7 + "T20:00:00.000+02:00"}},
                "copy": {"rich_text": [{"text": {"content": "Suite de pruebas: mcp."}}]},
                "media": {"files": [{"type": "file_upload", "file_upload": {"id": subir("t1.jpg")}, "name": "t1.jpg"}]}})
esperar_indice([pid_mcp])
c, antes = mcp({"operacion": "postiz", "fila": pid_mcp})
check("postiz de una fila sin post: ningún post y la ventana dicha", c == 200 and antes["posts"] == [] and antes["ventana"] == {"atras_dias": 30, "adelante_dias": 15}, "(%d)" % c)
c, s = mcp({"operacion": "sincronizar"}, espera=130)
check("sincronizar espera a que la pasada acabe", c == 200 and s == {"estado": "terminada"}, "(%d, %s)" % (c, s))
post_mcp = leer(pid_mcp)["post_id"]
c, despues = mcp({"operacion": "postiz", "fila": pid_mcp, "puntero": post_mcp})
posts_mcp = despues["posts"] if c == 200 else []
check("tras sincronizar, postiz ve el borrador, de la fila por identidad y por puntero",
      c == 200 and bool(post_mcp) and len(posts_mcp) == 1 and posts_mcp[0]["id"] == post_mcp and posts_mcp[0]["estado"] == "DRAFT"
      and sorted(posts_mcp[0]["coincide_por"]) == ["externalId", "postiz_post_id"], "(%d)" % c)
c, sin_puntero = mcp({"operacion": "postiz", "fila": pid_mcp})
check("sin puntero lo encuentra igual por la identidad externa", c == 200 and [p["coincide_por"] for p in sin_puntero["posts"]] == [["externalId"]], "(%d)" % c)
