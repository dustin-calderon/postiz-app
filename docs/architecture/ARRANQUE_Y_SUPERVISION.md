# ⚙️ Arranque y supervisión del contenedor

> **Estado**: ✅ Producción
> **Responsable de diseño**: Custom fork (`custom/postiz-dc`)
> **Relacionado**: [CONTENT_PIPELINE_NOTION_POSTIZ.md](./CONTENT_PIPELINE_NOTION_POSTIZ.md) · [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md)

Este documento existe porque el 2026-08-04 la API estuvo **2 h 38 min caída**
detrás de un contenedor que se declaraba `healthy`, y al investigarlo resultó
que nadie había mirado nunca esta capa. No trata de qué publica el sistema
—eso es el pipeline— sino de **cómo arrancan y quién vigila** los tres procesos.

---

## La cadena de arranque

Un solo contenedor, `postiz`, corre nginx y tres aplicaciones bajo PM2:

```
sh -c nginx && pnpm run pm2
  └─ pm2 delete all || true
     && pnpm run prisma-db-push
     && pnpm run --parallel pm2      ← arranca backend, frontend y orchestrator a la vez
     && pm2 logs
```

| App | Puerto | Lo que supervisa pm2 |
|---|---|---|
| `backend` | 3000 | `node dist/apps/backend/src/main.js` |
| `frontend` | 4200 | `next-server` |
| `orchestrator` | 3002 | `node dist/apps/orchestrator/src/main.js` |

nginx escucha en el **5000** y es la única puerta: `/api/*` va al backend y el
resto al frontend. Todo lo que se comprueba desde fuera pasa por ahí.

---

## La avería del 2026-08-04, y las cuatro cosas que la hicieron posible

Ninguna de las cuatro basta por sí sola. Encajaron en cadena, y por eso el
arreglo son cuatro cambios que se sostienen entre ellos.

### 1. El perfilador de Sentry colgaba el arranque

`apps/backend/src/main.ts` llama a `initializeSentry()` **antes que a nada**, y
ese módulo importaba `@sentry/profiling-node` en el nivel superior. Ese paquete
carga un binario nativo (`sentry_cpu_profiler.node`) al importarse, hubiera DSN
o no: la guarda que devuelve `null` estaba dentro de la función, demasiado tarde.

Evidencia de aquel arranque, con marcas de tiempo reales:

```
19:46:13.7  pm2 arranca backend (pid 164)
19:46:14.1  0|backend | > dotenv -e ../../.env -- node ... main.js
19:46:18.1  2|orchestrator | Starting Nest application...     ← el orchestrator tarda 4 s
            ────── 2 h 37 min 48 s sin una sola línea ──────
22:23:54    PM2 | Stopping app:backend id:0
22:23:55    PM2 | App [backend:0] exited with code [0] via signal [SIGKILL]
```

`Starting Nest application...` es lo primero que imprime `NestFactory.create()`,
después de todos los `require` de nivel superior. El proceso nunca llegó ahí:
se quedó en la fase de carga de módulos. El proceso colgado tenía **un solo**
módulo nativo cargado, `sentry_cpu_profiler.node`; uno sano carga seis.

> **No es determinista.** Cargar el grafo de Sentry aislado 10 veces en
> producción salió limpio las 10, en ~700 ms. Es una carrera al arrancar cuatro
> procesos node en cuatro núcleos. Por eso el arreglo es **no cargarlo**, no
> reordenarlo: `libraries/nestjs-libraries/src/sentry/initialize.sentry.ts`
> hace los dos `require` dentro de la función, después de la guarda del DSN.

### 2. pm2 no controlaba el proceso real

`pm2 start pnpm -- start` dejaba cuatro procesos por app:

```
pnpm  →  sh -c dotenv ...  →  dotenv  →  node main.js
```

pm2 sólo señaliza a su hijo directo, el envoltorio de pnpm. Un `pm2 stop`
dejaba el node real vivo y el puerto escuchando.

Ahora pm2 lanza el script con `--node-args`, así que **su hijo directo es el
proceso node**. `dotenv` desapareció del arranque en contenedor porque no hacía
nada: `/app/.env` no existe en la imagen y todo el entorno viene de `env_file`.
Se conserva la equivalencia con `--env-file-if-exists` para que `pnpm run pm2`
en local siga leyendo el `.env`.

### 3. pm2 arrancaba dos instancias en cada `restart`

Con `treekill: true` (el valor por defecto), pm2 7.0.1 invoca su callback de
muerte **dos veces** y arranca la app dos veces:

```
09:07:03.750  pid=181 msg=process tree killed (1 pids)
09:07:03.753  App [backend:0] starting in -fork mode-     ← arranque 1
09:07:03.754  pid=181 msg=process tree killed (1 pids)    ← el MISMO mensaje
09:07:03.755  App [backend:0] starting in -fork mode-     ← arranque 2
```

Reproducido aislado con una app de juguete, con caso de control:

| | `pm2 start` | `pm2 restart` | `pm2 delete` |
|---|---|---|---|
| `treekill: true` | 1 proceso | **2** | **deja 1 huérfano** |
| `--no-treekill` | 1 proceso | **1** | 0 |

> ### ⚠️ `--no-treekill` sólo es correcto junto al punto 2
> Con la cadena `pnpm → sh → dotenv → node` hacía falta matar el árbol para
> llegar al node real. **Revertir uno de los dos cambios sin el otro rompe.**
> El flag no sale en `pm2 start --help`; es la negación que commander genera
> para la opción `treekill`, y se verifica en `pm2 jlist` (`"treekill":false`).

### 4. Un backend que no podía escuchar se quedaba vivo

De las dos instancias, una coge el 3000 y la otra recibe `EADDRINUSE`. El
`catch` de `main.ts` lo logueaba y **seguía corriendo**. pm2 lo contaba como
`online` y podía acabar supervisando a ése en vez de al que sí tiene el puerto,
dejando al servidor real sin supervisor. Así es como un solo arranque llegó a
**seis backends simultáneos**.

Ahora hace `process.exit(1)`. Si de verdad no puede arrancar, el bucle de
reinicios **se ve**, que es justo lo que el comportamiento anterior ocultaba.

> ### ⚠️ El orden en que se arreglaron importa
> Con el `exit(1)` puesto pero sin `--no-treekill`, el zombi se convierte en un
> **bucle de reinicios que no para solo**: cada intento vive ~10 s, así que pm2
> no lo considera «inestable», `unstable_restarts` se queda en 0 y el tope de
> `max_restarts` nunca se alcanza. Se observó en producción: 14 reinicios y
> subiendo. Los cuatro cambios van juntos.

---

## El healthcheck

El anterior abría un socket TCP contra el 5000. **nginx puede estar vivo con el
backend muerto**, que es exactamente lo que pasó: el contenedor se declaró
`healthy` durante 2,5 h mientras la API devolvía 502.

El actual pide una URL real que atraviesa nginx **y** backend:

```yaml
healthcheck:
  test:
    - "CMD-SHELL"
    - "node -e \"require('http').get({host:'localhost',port:5000,path:'/api/auth/can-register',timeout:5000},function(r){process.exit(r.statusCode<500?0:1)}).on('error',function(){process.exit(1)})\""
  interval: 30s
  timeout: 10s
  retries: 5
  start_period: 120s
```

Vive en `/opt/homeserver/postiz/docker-compose.yml` (copia previa:
`docker-compose.yml.bak-20260805-healthcheck`). Se usa `node -e` porque la
imagen no trae `wget` ni `curl`. El compose, su `.bak` y `postiz.env` llevan
contraseñas y van en `600`, como el `.env` del homeserver. `build.sh` los edita
con `sed -i`, que conserva el modo.

> **`autoheal` no reinicia este contenedor.** Corre con
> `AUTOHEAL_CONTAINER_LABEL=autoheal` y `postiz` no lleva esa etiqueta. Un
> chequeo en rojo lo deja *unhealthy* y quieto — visible, pero sin bucle de
> reinicios. Si algún día se quiere que se auto-reinicie, hay que añadir la
> etiqueta a propósito.

**Quién avisa si cae y quién lo arregla:** el monitor `Postiz` de Uptime Kuma
avisa por Telegram y encola la caída en el bus de incidencias como
`kuma-postiz`. El triage la diagnostica con el runbook
`server/ops/postiz-caido.prompt.md`, que permite **un** reinicio de `postiz`
con diagnóstico previo, no un bucle. Qué pide el monitor y por qué, en
`docs/guides/UPTIME_KUMA_SETUP.md`; los dos, en Instalar-Home-Server.

---

## Cómo comprobar que un arranque fue bien

Hay un script de sólo lectura en `/opt/homeserver/postiz/verifica-arranque.sh`.
Lo que importa de su salida:

| Comprobación | Qué debe salir |
|---|---|
| `pm2 list` | tres apps `online` con `restarts=0` |
| pid de pm2 vs proceso real | `node …/main.js` y `next-server` — **nunca** `pnpm`, `sh` ni `dotenv` |
| procesos node vivos | uno por app, sin duplicados |
| `sentry_cpu_profiler` cargado | «no, en ninguno»: **no debe estar** en ningún proceso node |
| API y frontend por nginx | `HTTP 200` en `/api/auth/can-register`, `307` en `/` |
| datos | los mismos recuentos de `Media`, `Post` y ficheros que antes del despliegue |
| workflows vivos | los `postWorkflow…` de los posts programados siguen `Running`; «NO SE PUDO CONSULTAR» es un fallo, no un «no hay» |

Un arranque sano llega a `Backend is running` en **~12 s** desde que pm2 lanza
el proceso. Si pasa un minuto sin esa línea, no es lentitud: es el punto 1.

---

## Despliegue

**Fusionar a `custom/postiz-dc` despliega.** Cada 10 minutos el cron del
Beelink lanza `/opt/homeserver/postiz/desplegar.sh --si-hay-cambios`
([copia versionada](./scripts/desplegar.sh)). Si lo que corre no es el último
commit de la rama, y el cambio toca algo más que `docs/`, `.fork/`, `.github/`
o un `.md`, hace el despliegue entero:

1. trae la rama al clon (`/opt/repos/postiz-fork`, solo fast-forward);
2. construye la imagen con `build.sh`, que deja el compose apuntando a ella;
3. vuelca la base con `volcar-app.sh postiz` en `/opt/homeserver/ops/volcados-actualizacion/`;
4. recrea solo `postiz` (`up -d --no-deps`) y espera a que quede **sano**: el
   healthcheck en verde, las tres apps de pm2 `online`, `/` contestando 307 por
   nginx y el orchestrator del contenedor nuevo escuchando la cola `main` de
   Temporal;
5. si en 10 minutos no queda sano, vuelve solo a la imagen que corría y
   comprueba que esa sí lo esté.

Un despliegue bueno se cuenta por Telegram, con el commit y la imagen de
antes. Uno malo va al bus de incidencias (`postiz-despliegue`), que lo
diagnostica. El log, en `/opt/homeserver/ops/desplegar-postiz.log`.

A mano es lo mismo sin el flag. El build tarda unos 15 minutos, así que se
suelta del ssh, que por el túnel se corta:

```bash
ssh dchomeserver 'nohup /opt/homeserver/postiz/desplegar.sh >> /opt/homeserver/ops/desplegar-postiz.log 2>&1 < /dev/null &'
```

- **`build.sh`** ([copia versionada](./scripts/build.sh)) construye
  `postiz-custom:local-<sha>`. Una etiqueta por commit hace que los veredictos
  de `vulnerabilidades-aceptadas.json` (Instalar-Home-Server) caduquen con cada
  imagen: `check-imagenes-publicas.py` los vuelve a sacar esa noche y el triage
  los juzga otra vez, con las comprobaciones de `docs/DEUDA_TECNICA.md`.
- **El volcado va antes del `up -d` y se queda.** El arranque aplica el esquema
  con `prisma db push --accept-data-loss`, así que volver a la imagen anterior
  no deshace un cambio de esquema. Cómo se restaura, en la cabecera de
  `volcar-app.sh`.
- **`--no-deps` no es opcional.** Sin él, Compose también recrea postgres,
  redis, elasticsearch y Temporal si su configuración difiere de la de cuando
  se crearon. `up -d --dry-run postiz` enseña qué recrearía; con `--no-deps`,
  solo `postiz`.
- **Vuelta atrás a mano:** poner en la línea `image:` del compose la etiqueta
  que el aviso de Telegram da como «Antes corría» y repetir el
  `up -d --no-deps postiz`.
- **Las copias vivas** de `build.sh`, `verifica-arranque.sh` y `desplegar.sh`
  están en `/opt/homeserver/postiz` para que un push al repo no ejecute nada en
  el host sin que alguien las copie. Si se cambia una en el repo, se copia a
  mano; el aviso del despliegue dice si difieren. `desplegar.sh` se prueba
  entero, sin tocar nada real, con `bash docs/architecture/scripts/test_desplegar.sh`
  en Linux.

> **Recrear el contenedor no cambia la retención de medios.** `workflow.start`
> con un `workflowId` ya vivo lanza `WorkflowExecutionAlreadyStarted` y el
> `catch` se lo traga a propósito, así que `media-cleanup-workflow` sigue con el
> argumento con el que arrancó. Ver [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md).

---

## 🧹 Al depurar en este servidor: nada de volcados en `/tmp`

El 2026-08-05 se encontró `/tmp/postiz_dump.sql` de la sesión anterior: 119 KB,
**67 coincidencias de tokens de integración** y permisos `-rw-rw-r--`, es decir,
legible por cualquier proceso de la máquina y por cualquier contenedor que monte
`/tmp`. Eran los tokens vivos de las tres cuentas de Instagram.

`/tmp` no se limpia hasta el reinicio, y el servidor lleva **27 días** encendido.
Un volcado de `Integration` o de `Post` lleva credenciales aunque no lo parezca.

- Para consultar, `psql -Atc` contra el contenedor: no deja fichero.
- Si hace falta un fichero, escríbelo en el directorio del proyecto con `600` y
  bórralo al terminar.
- Comprobación rápida de que no quedó nada:
  ```bash
  grep -rlE 'IGAA[A-Za-z0-9]{20}|EAA[A-Za-z0-9]{20}|ntn_[A-Za-z0-9]{20}' /tmp 2>/dev/null
  ```

Los ficheros de trabajo que sí se conservan a propósito son las copias `.bak-*`
de lo que **no** está en git: `docker-compose.yml` y `postiz.env`. Todo lo demás
—scripts, suites— vive en `docs/architecture/scripts/`, así que una copia suelta
en el servidor sólo añade una versión más que puede divergir.

## ☠️ Borrar un canal borra su historial de publicaciones

**Nunca borres un canal para volver a conectarlo.** El botón de borrar de la UI
(`DELETE /integrations/`, `integrations.controller.ts:402-417`) hace esto:

```ts
const isTherePosts = await this._integrationService.getPostsForChannel(org.id, id);
if (isTherePosts.length) {
  for (const post of isTherePosts) {
    this._postService.deletePost(org.id, post.group).catch((err) => {});   // ← todos, incluidos los PUBLISHED
  }
}
return this._integrationService.deleteChannel(org.id, id);
```

Volver a añadir el canal **restaura la integración pero no los posts**: el
`upsert` de `createOrUpdateIntegration` va por `organizationId_internalId`, y el
`internalId` de Instagram no cambia, así que recupera la fila con su mismo `id`
y `deletedAt: null` — pero nadie deshace el borrado de los posts.

> **Pasó el 2026-08-05.** Se reconectaron los tres canales de Instagram
> borrándolos y volviéndolos a añadir, y desaparecieron del calendario los **19
> posts publicados**: 11 de CITEM a las 08:32:45 UTC y 8 de Dustin Compositor a
> las 08:36:46, cada bloque con un `deletedAt` idéntico al milisegundo —la firma
> de un borrado en cascada—, unos cuatro minutos antes de que cada canal se
> volviera a dar de alta. Se recuperaron poniendo `deletedAt = NULL`.

### El camino seguro para volver a pasar por OAuth

La UI sólo enseña «Channel disconnected, click to reconnect» cuando
`refreshNeeded` está activo (`launches.component.tsx:248-253`), y para un canal
sano no ofrece ninguna forma de repetir el OAuth. La hay, pero hay que
provocarla a mano:

```sql
-- marca el canal como "necesita reconexión"; NO toca los posts
UPDATE "Integration" SET "refreshNeeded" = true WHERE id = '<integrationId>';
```

Después, en la UI, el canal aparece con el aviso de reconectar: al pulsarlo se
repite el OAuth y `createOrUpdateIntegration` actualiza la fila en sitio. Los
posts no se tocan.

### Si ya se borraron

Es `deletedAt`, no un `DELETE`: se recupera. Restaura **sólo los `PUBLISHED`**
—ésos no se pueden republicar— y deja en paz los `QUEUE` y `ERROR`, que al
revivir podrían publicar o reintentar:

```sql
CREATE TABLE respaldo AS SELECT id, "deletedAt" FROM "Post"
  WHERE state = 'PUBLISHED' AND "deletedAt" BETWEEN '<inicio>' AND '<fin>';
UPDATE "Post" p SET "deletedAt" = NULL FROM respaldo r WHERE p.id = r.id;
```

Comprueba después que la **pasada de retirada no los vuelve a borrar**: lanza
`postiz-retirada-ig` y `postiz-sync-ig` y confirma que responden
`nada que hacer` y que el conteo de vivos no baja. El 2026-08-05 los 19
sobrevivieron a las dos.

---

## Cosas que parecen averías y no lo son

| Observación | Qué es de verdad |
|---|---|
| `Media.fileSize` es `0` en todas las filas | **Columna muerta.** En todo el repo aparece sólo en la línea de `schema.prisma` que la declara con `@default(0)`. Nadie la escribe ni la lee. Quitarla exigiría una migración en producción a cambio de nada |
| El TikTok tiene `tokenExpiration` en el pasado y ningún workflow de refresco | **Correcto.** `refreshCron` sólo lo declaran `instagram-standalone` y `threads`. Los demás proveedores refrescan bajo demanda, cuando un post falla con error de token |
| Filas de `Media` que apuntan a ficheros inexistentes | Esperado si están **soft-deleted**: el blob lo quita la Phase 1 y la fila espera a la Phase 2. Lo que sí sería un fallo es una fila **sin** `deletedAt` sin fichero — el 2026-08-05 había 29 del primer tipo y **cero** del segundo |
| Un fichero suelto en `/uploads` sin fila en `Media` | Probablemente un **avatar**. `Integration.picture` se guarda con `uploadSimple()`, que escribe el fichero y no crea fila en `Media`. Cada refresco de token escribe uno nuevo y abandona el anterior: ~5 KB por canal cada 58 días, y nada lo recoge. Se dejó así a propósito — un borrado automático por URL es más peligroso que 30 KB al año |

---

## Historial

### 2026-08-05 — los cuatro arreglos de arriba

Desplegados juntos porque se sostienen entre ellos. Verificado tras el
despliegue: arranque en 12 s, `sentry_cpu_profiler.node` ausente, un proceso por
app bajo pm2, `pm2 restart` deja **una** instancia, healthcheck HTTP en verde, y
los datos intactos (83 filas de `Media`, 67 posts, integraciones con el mismo
`id`).

Se aprovechó para retirar 3 avatares abandonados del disco (13,6 KB) tras
reconciliar los 61 ficheros contra la base: 54 con fila en `Media`, 4 avatares
en uso, 3 huérfanos. Quedan 58 y cero huérfanos.
