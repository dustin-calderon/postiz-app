# Plan — el MCP del pipeline de redes, para quien lleva las redes

> Transitorio: se borra al fusionar. Lo que queda vivo va al README del Worker, a [[CONTENT_PIPELINE_INVENTARIO|INVENTARIO]] y a [[CONTENT_PIPELINE_OPERACION|OPERACION]].

## Problema

La persona que lleva las redes (María) trabaja el calendario con su propia plaza de Claude: programar sus diseños, mover fechas, reordenar, lanzar el sync (el botón `Sync now` no se pulsa por API), saber qué ve Postiz de una pieza y dar parte de una avería del sistema. Sin acceso al repo ni al Beelink.

Es **invitada** en el Notion de Dustin, y Notion no deja conectar su MCP a un invitado («Only workspace members can connect Notion MCP», [guía oficial](https://developers.notion.com/guides/mcp/get-started-with-mcp)). Hacerla miembro cuesta una plaza de pago, y Dustin decidió no pagarla (2026-11-27). El calendario lo trabaja, por tanto, este MCP.

## Estrategia

```
Claude de María ──OAuth──► Worker `redes-mcp` ──token propio──► Notion: SOLO el calendario
                              │                                  (y lectura del manual)
                              └──1 secreto──► webhook n8n «Pipeline · MCP»
                                                 ├─ Postiz: estado de un post (diagnóstico)
                                                 ├─ sync (el workflow de siempre)
                                                 └─ bus de incidencias (alertar.sh)
```

- **El calendario, en el Worker, con una integración de Notion propia** (interna, de Dustin), conectada solo a la base *Calendario Social Media* y, en lectura, al manual. No la de n8n: un secreto en un solo sitio, que si cae solo alcanza el calendario. La lógica en TypeScript, versionada y con tests.
- **Lo que solo existe en el Beelink, por n8n**, que ya tiene sus credenciales: el estado en Postiz, el sync y el bus de incidencias.

### Herramientas del calendario

- `listar_calendario(desde, hasta, estado?)` y `leer_pieza(id)`.
- `crear_pieza(campos)` y `editar_pieza(id, campos)`, con una **lista cerrada de propiedades escribibles**: las que el manual da a las personas (título, `Fecha`, `cuenta`, `Plataforma`, `Tipo`, `copy`, `first_comment`, `colaboradores`, `is_trial_reel`, `Notas`, `URL`, `cuenta origen`) y `Status` solo con los valores de las personas (`Por replicar`, `Por aprobar`, `Listo`, o vacío para retirar). Nunca las columnas ❌ ni los estados que escribe la máquina (`Programado`, `Publicado`, `Error`). La validación de fondo (hora, ficheros, trial reel…) sigue siendo la del sync, que deja `Error` con el motivo: el MCP no la duplica.
- **Subir diseños** (`preparar_subida` → partes → `adjuntar_media`): Claude Code trocea el fichero en partes de ~10 MB y las manda al Worker, que las reenvía a la [subida por partes de Notion](https://developers.notion.com/guides/data-apis/sending-larger-files) (partes de 5–20 MB, hasta 5 GB en un espacio de pago). Cada envío al Worker queda muy por debajo de su límite de cuerpo (100 MB) y de memoria (128 MB) ([límites](https://developers.cloudflare.com/workers/platform/limits/)). La URL de cada subida es de un solo uso, firmada y ligada a quien la pidió y a esa subida; el token de Notion no sale del Worker. `adjuntar_media` fija el orden de `media`, que es el del carrusel. Solo en Claude Code, que lee ficheros locales; desde la app, los ficheros se arrastran a la fila en Notion.

- **Worker aparte**, hermano de `dustin-mcps` en `personal-context-server/servers/`, con el OAuth compartido (`_shared/oauth`). No dentro de `dustin-mcps`: allí un login abre Empresas, Libro, Transfer, CRM y Firmas. Su lista de correos admitidos es María y Dustin; su app de Access, propia, para que la política que admite a María no toque la de `dustin-mcps`.
- **La lógica en n8n.** El Worker guarda **un** secreto que solo sirve para tres operaciones fijas. Las credenciales de Notion, Postiz y el sync se quedan donde ya están (n8n), sin copias que rotar ni una clave de Postiz que publique desde Cloudflare.
- **Tres herramientas:**
  - `diagnosticar(fila)`: hechos, no veredictos — la fila de Notion (estado, fecha, `❌ error_log`, `❌ postiz_post_id`) y lo que Postiz tiene de ella (estado del post o que no existe), más si cae en la ventana de 15 días. La explicación la da Claude con el manual; el pipeline no se reimplementa aquí.
  - `sincronizar()`: lanza el sync de siempre y espera a que acabe (el `Sync now`).
  - `reportar_averia(descripcion, fila?)`: encola en el bus de incidencias con un origen propio; lo recoge el triage del Beelink.
- **Las reglas viven en el manual de Notion.** Las instrucciones del MCP solo dicen dónde mirar y lo que no es derivable: leer el manual antes de tocar el calendario; `Listo` aprueba y solo lo pone una orden de la persona; las columnas ❌ no se tocan; tras sincronizar, `diagnosticar`.

## Riesgos y límites

- **El secreto del Worker** abre tres operaciones: leer una fila y su post, lanzar un sync, encolar una incidencia. Ninguna publica ni borra. Se rota en los dos sitios a la vez (INVENTARIO §2).
- **El bus de incidencias** solo acepta orígenes `n8n-*` por la clave SSH de n8n; el reporte entra por ahí, sin abrir un receptor nuevo. El triage no le contesta a quien reporta: la respuesta, por ahora, es que el sistema lo revisa.
- **Por comprobar en la primera prueba con su cuenta:** que la app de claude.ai entrega las instrucciones del servidor, y que un conector personalizado del Team aparece en su plaza.
