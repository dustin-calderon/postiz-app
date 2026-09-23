# Deuda técnica

Lo que se sabe pendiente en `custom/postiz-dc` y se ha decidido no resolver todavía. Cada entrada dice por qué se aplaza, qué la haría urgente y cómo se cierra. Al cerrarla se borra de aquí: el commit que la resuelve es su registro.

**Contexto común a todas.** Postiz se publica en `https://postiz.dustincalderon.com` detrás de Cloudflare Access, con el registro cerrado (`DISABLE_REGISTRATION=true`). Qué queda fuera de Access y por qué lo dice su entrada en `Instalar-Home-Server/server/config/apps-publicas.json`. Hay dos excepciones:

- `/uploads`: nginx lo sirve como fichero estático.
- `/api/public/v1/*`: llega al backend sin login y exige la API key de la organización (`PublicAuthMiddleware`). El resto de `/api/public` (`PublicController`) pide Access como todo lo demás: lo llama el frontend.

El contenedor solo publica nginx, en `127.0.0.1:4007`. Todo lo de abajo se ha juzgado con ese montaje: si cambia, cambia el juicio. Se comprueba así:

```bash
for p in '/_next/image?url=%2Ffavicon.ico&w=64&q=75' /api/auth/can-register /api/enterprise/create-user /api/public/stream; do
  curl -s -o /dev/null -w "$p %{http_code} %{redirect_url}\n" "https://postiz.dustincalderon.com$p"; done
# las cuatro: 302 a cloudflareaccess.com
curl -s -o /dev/null -w '%{http_code}\n' https://postiz.dustincalderon.com/api/public/v1/is-connected
# 401: llega al backend y pide la API key
```

---

## Credenciales generadas con `Math.random`: hay que rotarlas

**Qué pasa.** Hasta `8fb61ee4` (arreglo portado de PSA-2026-TD98KY) las API keys de organización salían de `Math.random`. Además, `POST /api/public/t` estuvo abierto sin login hasta el 23-09-2026 y devuelve en la cookie `track` un `makeId(10)`, que son diez salidas de ese mismo generador por petición. Quien las recogiera en bloque mientras vivía un proceso del backend podía reconstruir su estado y predecir las credenciales que ese proceso generara. No se puede demostrar que nadie lo hiciera. Las credenciales nuevas ya salen de `crypto`, y lo que `/t` siga filtrando ya no predice nada.

**Cómo se cierra.** Regenerando cada API key creada antes del despliegue de `8fb61ee4` (pantalla de API pública, `POST /user/api-key/rotate`) y actualizando en n8n la de la organización que usa. Se listan con:

```bash
docker exec postiz-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select name, \"updatedAt\" from \"Organization\" where \"apiKey\" is not null"'
```

---

## Dependencias críticas que se despliegan y solo se arreglan saltando de versión mayor

**Qué pasa.** Dependabot y trivy señalan dos críticas de ejecución que no tienen arreglo dentro de la versión mayor que se usa:

| Paquete | Aviso | Quién lo trae | Arreglo |
|---|---|---|---|
| `tar` 6.x | GHSA-23hp-3jrh-7fpw / CVE-2026-59873 | `@mapbox/node-pre-gyp`, vía `bcrypt` y `canvas` | solo en `tar` 7 |
| `happy-dom` 15.x | GHSA-37j7-fg3j-429f / CVE-2025-61927 | `@wyw-in-js/transform`, vía `@pigment-css/react` | solo en `happy-dom` 20 |

**Por qué no se arreglan con un override.** Forzar una versión mayor por debajo de quien la pide rompe su API sin aviso, y aquí no hay prueba que lo detectara antes de producción.

**Por qué no son alcanzables** (se despliegan, pero nada les llega):

- `tar` solo lo usa `node-pre-gyp` para desempaquetar binarios nativos durante `pnpm install`. En ejecución, `bcrypt` solo le pide la ruta del binario ya instalado. Esto tiene que imprimir `false`:
  `docker exec -w /app/apps/backend postiz node -e 'require("bcrypt"); console.log(Object.keys(require.cache).some(k => /node_modules\/tar\//.test(k)))'`
- `happy-dom` lo usa `@wyw-in-js/transform` para evaluar el CSS-in-JS de `@pigment-css` durante `next build`, sobre nuestro propio código. Esto no tiene que imprimir nada:
  `docker exec postiz sh -c 'grep -rl happy-dom /app/apps/frontend/.next/server /app/apps/backend/dist /app/apps/orchestrator/dist'`

En Dependabot, sus avisos (críticos, altos y medios) están descartados como `tolerable_risk` con este motivo. En trivy, aceptadas en `vulnerabilidades-aceptadas.json` atadas a la imagen, así que cada build nuevo las vuelve a sacar y se juzgan otra vez con estas dos comprobaciones.

**Qué la vuelve urgente.** Que algo en ejecución empiece a cargar `tar` o `happy-dom` (una importación de archivos, un renderizado de HTML en el servidor), o un aviso nuevo sobre ellos que no necesite ese camino.

**Cómo se cierra.** Cuando quien los trae suba de mayor (`node-pre-gyp` 2 usa `tar` 7; `@wyw-in-js/transform` 2.5 usa `happy-dom` 20), o con la imagen de producción de la entrada siguiente.

---

## La imagen de producción lleva herramientas de desarrollo que no ejecuta

**Qué pasa.** `Dockerfile.dev` hace un `pnpm install` completo con devDependencies, instala `pnpm` y `pm2` con npm y compila dentro de la imagen. Además, `next` deja la caché de Turbopack en `apps/frontend/.next/cache`. Por eso trivy encuentra críticas en código que no se ejecuta: el runtime de Go dentro de `esbuild` y el `tar` que traen npm y pnpm. En ejecución solo corren `next-server`, el backend, el orchestrator, pm2 y pnpm. pnpm solo lanza los scripts de arranque, y lo único que baja (`pnpm dlx prisma`) viene del registro de npm por TLS. La lista de cada imagen, con su motivo, está en `vulnerabilidades-aceptadas.json`.

**Por qué se aplaza.** Pasar a una imagen de varias etapas (compilar en una y copiar a otra solo lo que se ejecuta) cambia el arranque (`pm2-run`, `prisma db push`, nginx) y exige probarlo a fondo.

**El coste de no hacerlo.** Cada build vuelve a sacar estos hallazgos y hay que aceptarlos a mano otra vez: es el precio de que las aceptaciones caduquen.

**Qué la vuelve urgente.** Que ese coste se note: más de un build al mes, o que la lista crezca.

**Cómo se cierra.** Un `Dockerfile` de producción sin devDependencies ni herramientas de build, construido por `build.sh`, y el escáner de imágenes sin esos hallazgos.

---

## Protección SSRF de salida de upstream, sin portar

**Qué pasa.** Upstream filtra las URLs internas en los webhooks, en los proveedores con URL propia (Mastodon, Lemmy, WordPress…) y en las descargas de medios por URL (`db65072f`, `05b05fc5`, `1e4c8dd5`, `6c4a8ca4`). Aquí solo está el `ssrfSafeDispatcher` base, que usa `/public/stream`. Sin el resto, quien pueda dar una URL a Postiz puede hacer que el servidor pida recursos de la red de casa o de otros contenedores.

**Por qué se aplaza.** Exige una cuenta de Postiz (detrás de Access) o la API key de la organización (n8n). Portarlo choca con el código de subida propio (streaming, `upload-from-url`), así que no es un cherry-pick.

**Qué la vuelve urgente.** Que alguien fuera del equipo reciba una cuenta o una API key, o que se abra el registro.

**Cómo se cierra.** Portando `getSsrfSafeDispatcher` y `getSsrfSafeAxios` y aplicándolos donde este código pide URLs que da el usuario.

---

## El lint de la raíz no pasa sobre el código existente

**Qué pasa.** La configuración carga (ESLint 9), pero `npx eslint apps libraries`, desde la raíz, sale con errores de código que ya existía. Casi todos son reglas de React Compiler que `eslint-plugin-react-hooks` 7 trae como error dentro de `next/core-web-vitals`. Además:

- `apps/frontend/public/f.js` es un bundle estático, y nada lo excluye del lint.
- `usePageVisibility` (`libraries/react-shared-libraries/src/helpers/use.is.visible.tsx`) no lo usa nadie. Incumple `rules-of-hooks`, y su limpieza no quita los listeners de `blur` y `focus`.
- La raíz declara devDependencies de lint que `eslint.config.mjs` no importa (`@typescript-eslint/*` 7, `eslint-plugin-react`, `eslint-plugin-react-hooks` 4, `eslint-plugin-import`, `eslint-plugin-jsx-a11y`). ESLint 9 ignora `libraries/nestjs-libraries/.eslintrc.json` y `libraries/react-shared-libraries/.eslintrc.json`.

**Qué la vuelve urgente.** Que el lint tenga que hacer de puerta (CI, o antes de desplegar). Hoy no puede.

**Cómo se cierra.** Borrar `usePageVisibility`, excluir `apps/frontend/public/` y decidir si las reglas de React Compiler son error o aviso. Luego, limpiar las devDependencies y los `.eslintrc.json` que sobran, y arreglar lo que quede hasta que `npx eslint apps libraries` salga con 0.
