# Plan — el MCP del pipeline de redes, para quien lleva las redes

> Transitorio: se borra al fusionar. Lo que queda vivo va al README del Worker, a [[CONTENT_PIPELINE_INVENTARIO|INVENTARIO]] y a [[CONTENT_PIPELINE_OPERACION|OPERACION]].

## Problema

La persona que lleva las redes (María) trabaja el calendario con su propia plaza de Claude: programar sus diseños, mover fechas, reordenar. Eso ya lo hace el **conector oficial de Notion** de su cuenta, con sus permisos de Notion. Lo que no puede es lo que no está en Notion: lanzar el sync (el botón `Sync now` no se pulsa por API), saber qué ve Postiz de una pieza y dar parte de una avería del sistema. Sin acceso al repo ni al Beelink.

## Estrategia

```
Claude de María ──OAuth──► Worker `redes-mcp` ──1 secreto──► webhook n8n «Pipeline · MCP»
   │                         (solo identidad y          (la lógica, con las credenciales
   └──conector de Notion──►   tres herramientas)         que n8n ya tiene)
        (el calendario)                                        │
                                                               ├─ Notion + Postiz: diagnóstico
                                                               ├─ sync (el workflow de siempre)
                                                               └─ bus de incidencias (alertar.sh)
```

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
