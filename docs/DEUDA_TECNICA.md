# Deuda técnica del fork

Lo que se sabe pendiente en `custom/postiz-dc` y se ha decidido no resolver todavía. Cada entrada dice por qué se aplaza, qué la haría urgente y cómo se cierra. Al cerrarla se borra de aquí: el commit que la resuelve es su registro.

Contexto común a todas: Postiz se publica en `https://postiz.dustincalderon.com` detrás de Cloudflare Access; solo entran el owner y su equipo, y el registro está cerrado (`DISABLE_REGISTRATION=true`). Access deja fuera dos rutas. La primera es `/uploads`, que nginx sirve como fichero estático porque las redes sociales descargan de ahí los medios. La segunda, `/api/public/*` entera, llega al backend sin login. Allí solo `/api/public/v1/*` exige la API key de la organización (`PublicAuthMiddleware`; la usa n8n). El resto de `PublicController` responde a cualquiera: `GET /posts/:id` y `/posts/:id/comments` (vista previa), `POST /t` (seguimiento), `GET /stream`, `POST /modify-subscription` y `POST /agent`, que no hace nada sin `AGENT_API_KEY`, sin definir aquí. El contenedor solo publica nginx, en `127.0.0.1:4007`. Todo lo de abajo se ha juzgado con ese montaje: si cambia, cambia el juicio. Se comprueba con

```bash
for p in '/_next/image?url=%2Ffavicon.ico&w=64&q=75' /api/auth/can-register /api/enterprise/create-user; do
  curl -s -o /dev/null -w "$p %{http_code} %{redirect_url}\n" "https://postiz.dustincalderon.com$p"; done
```

y las tres tienen que redirigir a `cloudflareaccess.com`, mientras que `curl -s -o /dev/null -w '%{http_code}\n' https://postiz.dustincalderon.com/api/public/v1/is-connected` tiene que dar `401` (llega al backend y pide la API key).

---

## Dependencias críticas que se despliegan y solo se arreglan saltando de versión mayor

**Qué pasa.** Dos críticas de ejecución siguen abiertas en Dependabot y en el escáner de imágenes (trivy):

| Paquete | Aviso | Quién lo trae | Arreglo |
|---|---|---|---|
| `tar` 6.2.1 | GHSA-23hp-3jrh-7fpw / CVE-2026-59873 (DoS por gzip bomb) | `@mapbox/node-pre-gyp`, vía `bcrypt` y `canvas` | solo en 7.5.19 |
| `happy-dom` 15.11.7 | GHSA-37j7-fg3j-429f / CVE-2025-61927 (escape del contexto VM) | `@wyw-in-js/transform`, vía `@pigment-css/react` | solo en 20.0.0 |

**Por qué no se arreglan con un override.** Forzar una versión mayor por debajo de quien la pide rompe su API sin aviso, y aquí no hay prueba que lo detectara antes de producción.

**Por qué no son alcanzables aquí** (se despliegan, pero nada les llega):

- `tar` 6.2.1 solo lo usa `node-pre-gyp` para desempaquetar los binarios nativos durante `pnpm install`, en el build. En ejecución, `bcrypt` solo le pide la ruta del binario ya instalado. Comprobado el 2026-09-23: después de `require("bcrypt")`, `tar` no está en `require.cache`. No hay ninguna vía por la que un tar ajeno llegue a desempaquetarse.
- `happy-dom` lo usa `@wyw-in-js/transform` para evaluar el CSS-in-JS de `@pigment-css` durante `next build`, sobre nuestro propio código. No aparece en ningún bundle de ejecución (`apps/frontend/.next/server`, `apps/backend/dist`, `apps/orchestrator/dist`). En ejecución solo corren `next-server`, el backend, el orchestrator, pm2 y pnpm (se comprueba con `docker exec postiz sh -c 'for p in /proc/[0-9]*; do tr "\0" " " < $p/cmdline; echo; done'`).

En Dependabot se descartan como `tolerable_risk` con este motivo. En trivy se aceptan en `Instalar-Home-Server/server/config/vulnerabilidades-aceptadas.json`, atadas a la imagen (`postiz-custom:local-<sha>`), así que cada build nuevo las vuelve a sacar y hay que juzgarlas otra vez.

**Qué la vuelve urgente.** Que algo en ejecución empiece a importar `tar` o `happy-dom` (una función de importar archivos, un renderizado de HTML en el servidor), o un aviso nuevo sobre ellos que no necesite ese camino.

**Cómo se cierra.** Cuando quien los trae suba de mayor (`node-pre-gyp` 2.x usa `tar` 7; `@wyw-in-js/transform` actual usa `happy-dom` 20), o con la imagen de producción de la entrada siguiente, que los deja fuera.

---

## La imagen de producción lleva herramientas de desarrollo que no ejecuta

**Qué pasa.** `Dockerfile.dev` hace un `pnpm install` completo con devDependencies, instala `pnpm` y `pm2` con npm y compila dentro de la imagen. Por eso trivy encuentra críticas en código que no se ejecuta: `vitest` 3.1.4 (CVE-2026-47429), `handlebars` 4.7.8 de `ts-jest` (CVE-2026-33937), la stdlib de Go 1.23 dentro del binario de `esbuild` (CVE-2025-68121) y el `tar` que traen npm y pnpm (CVE-2026-59873). Ninguno corre en producción. pnpm solo ejecuta los scripts de arranque, y el único paquete que baja (`pnpm dlx prisma@6.5.0`) viene por TLS del registro de npm.

**Por qué se aplaza.** Pasar a una imagen de varias etapas (compilar en una y copiar a otra solo lo que se ejecuta) cambia el arranque (`pm2-run`, `prisma db push`, nginx) y hay que probarlo a fondo. No cabe en el cierre de vulnerabilidades del 2026-09-23. Estas cuatro se aceptan en `vulnerabilidades-aceptadas.json` atadas a la imagen.

**El coste de no hacerlo.** Cada build vuelve a sacar estos hallazgos, que hay que aceptar a mano otra vez. Es el precio de que las aceptaciones caduquen.

**Qué la vuelve urgente.** Que ese coste se note: más de un build al mes, o que la lista crezca.

**Cómo se cierra.** Un `Dockerfile` de producción que deje fuera las devDependencies y las herramientas de build, construido por `build.sh`, y el escáner de imágenes sin esos hallazgos.

---

## Arreglos de seguridad de upstream revisados y no portados

Desde el 2026-09-23 esto es producto propio (`.fork/STRATEGY.md`): de `gitroomhq/postiz-app` solo se portan los arreglos de seguridad. Revisado hasta `v2.24.0` (el vigilante de versiones de Instalar-Home-Server compara con esa marca, en `apps-publicas.json`). Portados: `387d85da` (PSA-2026-NWZN9J), `9259cf24` (PSA-2026-P8W1J0 / CVE-2026-94455), `4c835138` (PSA-2026-TD98KY / CVE-2026-94456) y `79360622` (path traversal en `/api/uploads` de Next). Revisados y **no** portados:

**Protección SSRF de salida** (`db65072f`, `05b05fc5`, `1e4c8dd5`, `6c4a8ca4`). Upstream filtra las URLs internas en los webhooks, en los proveedores con URL propia (Mastodon, Lemmy, WordPress…) y en las descargas de medios por URL. Sin eso, quien pueda dar una URL a Postiz puede hacer que el servidor pida recursos de la red de casa o de otros contenedores. Aquí eso exige una cuenta de Postiz (detrás de Access) o la API key de la organización (n8n). Portarlo choca con el código de subida propio de este fork (streaming, `upload-from-url`), así que no es un cherry-pick. **Se vuelve urgente** si alguien fuera del equipo recibe una cuenta o una API key, o si se abre el registro. **Se cierra** portando `getSsrfSafeDispatcher` y `getSsrfSafeAxios` de upstream y aplicándolos donde este fork pide URLs que da el usuario. El `ssrfSafeDispatcher` base ya está aquí: lo usa `/public/stream`.

**Paquetes con avisos altos que upstream subió en `7a02bd6b`** (`multer`, entre otros). Son altas, no críticas, y quedan con el resto de altas en la entrada siguiente.

**Credenciales generadas antes del 2026-09-23: hay que rotarlas.** Las API keys de organización salieron de `Math.random`. Además, `POST /api/public/t`, sin login, devuelve en la cookie `track` un `makeId(10)`: diez salidas de ese mismo generador por petición. Es el vector de PSA-2026-TD98KY. Quien las hubiera recogido en bloque mientras vivía un proceso del backend podía reconstruir su estado y predecir las credenciales que ese proceso generara. No se puede demostrar que nadie lo hiciera. Inventario del 2026-09-23: 0 apps OAuth, 0 autorizaciones OAuth y 3 API keys de organización (Test, y dos de CITEM). Desde `8fb61ee4` las credenciales nuevas salen de `crypto`, y lo que `/t` filtre ya no sirve para predecir nada. **Se cierra** regenerando las tres después del despliegue (pantalla de API pública, `POST /user/api-key/rotate`) y actualizando en n8n la de la organización que usa.

---

## Avisos altos y medios de Dependabot sin revisar

**Qué pasa.** A 2026-09-23 hay unos 150 avisos altos y 150 medios de ejecución abiertos. Entre otros: `multer`, `nodemailer` y `sharp`, con PR de Dependabot abierto; `axios`, `undici`, `fast-uri`, `hono`, `js-yaml`, `nanoid` y `brace-expansion`. `check-dependencias-publicas.py` solo mira las críticas, a propósito, y nadie ha revisado estas una a una.

**Por qué se aplaza.** El cierre del 2026-09-23 tenía un alcance acotado: las críticas antes de que los vigilantes empezaran a avisar el 30-09.

**Cómo se cierra.** Revisando primero los paquetes directos que tocan datos de fuera: `multer` (subidas), `nodemailer` (correo), `sharp` (imágenes) y `axios`. Para cada uno, subirlo dentro de su mayor o descartar el aviso en GitHub con su motivo. Después, los transitivos por quien los trae.
