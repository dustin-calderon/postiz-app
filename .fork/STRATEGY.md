# Estrategia — `dustin-calderon/postiz-app`

> **Origen:** `https://github.com/gitroomhq/postiz-app` (remote `upstream`)
> **Repo:** `https://github.com/dustin-calderon/postiz-app`, rama `custom/postiz-dc` (la de por defecto)
> **Producción:** Beelink, `/opt/repos/postiz-fork` → `/opt/homeserver/postiz/build.sh`
> **Decisión vigente:** 2026-09-23, del owner

---

## Producto propio, no fork que sigue a upstream

Hasta junio de 2026 este repo era un *patch stack*: pocos commits propios que se
rebasaban sobre cada release de upstream. Eso dejó de ser verdad. Sobre `v2.21.9`
se apilaron 127 commits propios (carpetas de medios, limpieza automática, subida
por streaming, identidad externa del post, webhooks de fallo, el workflow de
Temporal `postWorkflowV106`, el pipeline con Notion y n8n…). Rebasarlos sobre
`v2.24.0` daba 32 archivos en conflicto, un `schema.prisma` con 882 líneas nuevas
arriba y un `postWorkflowV106` de upstream con el mismo nombre que el nuestro y
distinto código, que habría roto los posts ya programados en Temporal.

Desde el 2026-09-23 este código es **nuestro**: no se rebasa ni se sigue la
numeración de upstream. De upstream solo se traen **arreglos de seguridad**.

## Cómo se traen los arreglos de seguridad

1. `check-apps-publicas-version.sh` (Instalar-Home-Server) compara las releases de
   upstream con `version.revisado` de la entrada `postiz` en
   `server/config/apps-publicas.json`: la última release cuyos arreglos de
   seguridad ya se han mirado. Si hay una más nueva, avisa al bus.
2. Se leen las notas de la release y los commits de seguridad desde la marca
   (`git log --no-merges -i -E --grep="secur|ssrf|cve|vuln|xss|traversal|inject|harden" <revisado>..<nueva>`).
3. Cada uno se **porta**, con `git cherry-pick -x` si entra y a mano si no,
   manteniendo nuestro código y aplicando solo su cambio, o se **descarta**
   escribiendo por qué en `docs/DEUDA_TECNICA.md`, con lo que lo reabriría.
4. Se sube `version.revisado` en el registro.

Las dependencias no dependen de upstream: las vigila Dependabot en este repo, y
las críticas se arreglan aquí (`pnpm.overrides`) o se descartan con su motivo.

## Qué se ha revisado

Hasta `v2.24.0`, el 2026-09-23. Lo portado y lo descartado está en
`docs/DEUDA_TECNICA.md` («Arreglos de seguridad de upstream revisados y no
portados») y en los commits con `(cherry picked from commit …)`.

## Despliegue

`docs/architecture/ARRANQUE_Y_SUPERVISION.md` → «Despliegue». Resumen:
`git pull` en el Beelink, `build.sh` (construye `postiz-custom:local-<sha>` y deja
el compose apuntando a ella), volcado de la base (el arranque hace
`prisma db push --accept-data-loss`) y `docker compose … up -d postiz`.
