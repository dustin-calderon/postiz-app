# Estrategia — `dustin-calderon/postiz-app`

> **Origen:** `https://github.com/gitroomhq/postiz-app` (remote `upstream`)
> **Producción:** rama `custom/postiz-dc` (la de por defecto) → Beelink, `/opt/repos/postiz-fork`

## Producto propio

Este código nació de `gitroomhq/postiz-app`, pero es nuestro. No se rebasa sobre
upstream ni sigue su numeración, y lo decidió el owner el 2026-09-23. Las razones
no caducan con una release:

- **Tiene funciones propias** que tocan el núcleo: carpetas de medios, limpieza
  automática, subida por streaming, identidad externa del post, webhooks de
  fallo y el pipeline con Notion y n8n. Cada rebase sería un proyecto entero de
  resolver conflictos.
- **Los workflows de Temporal comparten nombres con los de upstream.** Upstream
  publicó su propio `postWorkflowV106`, con otro código que el nuestro. Traer uno
  de sus workflows exige ponerle un nombre que no exista aquí; si no, rompe los
  posts ya programados.

## Qué se trae de upstream

**Los arreglos de seguridad** que alcancen este código, salvo los que
`docs/DEUDA_TECNICA.md` decide no portar, con su motivo y lo que lo reabriría.
**El resto** de arreglos, mejoras y funciones **solo se propone**, y lo decide
el owner.

Lo hace el triage del Beelink cuando el vigilante de versiones avisa de una
release nueva, siguiendo `Instalar-Home-Server/server/ops/actualizar-app-publica.prompt.md`
(sección «Apps `revisado`»): deja una rama `revision/<release>` y un informe.
Cada dato vive en un solo sitio:

| Qué | Dónde |
|---|---|
| Hasta qué release está revisado | `version.revisado` de la entrada `postiz` en `Instalar-Home-Server/server/config/apps-publicas.json` |
| Qué se portó | `git log --grep "cherry picked from"`, y los ports a mano, que lo dicen en su mensaje |
| Qué seguridad no se porta, y por qué | `docs/DEUDA_TECNICA.md` |

Las dependencias no dependen de upstream: las vigila Dependabot en este repo, y
cada aviso se arregla aquí (subiendo la dependencia o con un `pnpm.overrides` de
suelo) o se descarta en GitHub con su motivo.

## Despliegue

`docs/architecture/ARRANQUE_Y_SUPERVISION.md`, sección «Despliegue».
