# Deuda técnica del fork

Lo que se sabe pendiente en `custom/postiz-dc` y se ha decidido no resolver todavía. Cada entrada dice por qué se aplaza, qué la haría urgente y cómo se cierra. Al cerrarla se borra de aquí: el commit que la resuelve es su registro.

---

## Next vulnerable a GHSA-2xp9-vwfh-vxw4 (RCE por AVIF en el optimizador de imágenes)

**Qué pasa.** El advisory [GHSA-2xp9-vwfh-vxw4](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4) (crítico) es una ejecución remota de código en la API de optimización de imágenes de Next al procesar un AVIF, heredada de `libheif` a través de `sharp`. Afecta a `next >= 16.0.0, < 16.3.3` y `>= 10.0.0, < 15.5.24`. Este fork fija `next` en `16.2.6` (`package.json`, tanto la dependencia como `pnpm.overrides`), y es la única versión de `next` que resuelve `pnpm-lock.yaml`. Postiz se publica en `https://postiz.dustincalderon.com` sin Cloudflare Access delante.

**Por qué importa.** El Beelink ya fue comprometido el 13-09-2026 por una RCE de Next en otra aplicación sin parchear (`Instalar-Home-Server/docs/research/INCIDENTE-2026-09-13-MINERO-TICKETERA.md`, §7 fila 2). No es un riesgo teórico en esta máquina.

**Por qué se aplaza (decisión del owner, 21-09-2026).** El registro de Postiz está cerrado. `apps/frontend/next.config.js` no declara `images.remotePatterns` ni `images.domains`, así que el optimizador solo acepta imágenes locales. Para que procese un AVIF malicioso, alguien tendría que subirlo antes. Subir exige sesión iniciada (`MediaController` pasa por `AuthMiddleware`) o una API key de la organización (la API pública pasa por `PublicAuthMiddleware`). El advisory lo llama «unauthenticated» porque, en general, basta con que el AVIF llegue a una fuente permitida. Aquí la única fuente permitida es la de las subidas.

**Qué la vuelve urgente.** Cualquiera de estas señales:

- Se abre el registro, o aparece otra vía para subir ficheros sin sesión.
- Aparece un exploit que no necesita subir el fichero ni tener sesión.
- Sale una release de Postiz que ya trae un Next corregido.

**Cómo se cierra.** Hay dos caminos:

- Subir `next` en el fork a una versión corregida (`>= 16.3.3` en la rama 16), en la dependencia y en `pnpm.overrides`. Después se regenera el lockfile y se reconstruye con `build.sh`.
- Rebasar `custom/postiz-dc` sobre una release de upstream que ya la traiga. En el momento de la decisión, ninguna la traía: `v2.23.0`, la última release, fija `16.2.6`, y `upstream/main` fija `16.3.1`, que también es vulnerable.

Se da por cerrada cuando `pnpm-lock.yaml` solo resuelve un `next` fuera de los rangos afectados y la imagen desplegada se ha construido desde ese commit.

`Instalar-Home-Server/server/ops/check-apps-publicas-version.sh` avisa de las releases nuevas de Postiz, pero ese aviso puede cambiar de mecanismo. Por eso las señales de arriba hay que revisarlas aunque no llegue ningún aviso.
