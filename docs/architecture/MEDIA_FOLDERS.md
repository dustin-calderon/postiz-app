# 🗂️ Carpetas de medios

> **Relacionado**: [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md) — la limpieza automática borra medios, y una carpeta deja de existir cuando se queda sin medios vivos.

La biblioteca de medios se organiza en carpetas **virtuales**: no hay tabla de
carpetas, sólo un campo de texto en cada medio. La jerarquía (`Marca/Sub`) es
una convención del texto, no una relación en la base de datos. Este documento
explica ese modelo, las reglas que lo sostienen, el contrato de la API y dónde
vive cada pieza.

---

## El modelo: una carpeta es un valor de `Media.folder`

`Media` tiene un campo `folder String?` con su propio índice (`@@index([folder])`).
No existe un modelo `Folder`.

| Valor de `folder` | Significado |
|---|---|
| `null` | Sin carpeta (la «raíz») |
| `"Citem"` | Carpeta de primer nivel — la UI la llama *marca* |
| `"Citem/Diseños"` | Subcarpeta `Diseños` dentro de `Citem` |

El separador es `/`. El backend no limita la profundidad: `"A/B/C"` es un valor
válido, y el renombrado en cascada lo trata igual que a los demás. La interfaz,
en cambio, sólo dibuja dos niveles (ver más abajo).

De ahí salen tres consecuencias que conviene tener presentes:

- **Una carpeta existe mientras haya al menos un medio vivo con ese valor
  exacto.** La lista de carpetas se deriva de los medios no borrados
  (`deletedAt IS NULL`) de la organización. Si se mueven o se borran todos los
  medios de una carpeta, desaparece sola: no hay huérfanos que limpiar.
- **No puede existir una carpeta vacía en el servidor.** Por eso crear una
  carpeta en la UI no llama a la API: la carpeta nueva vive sólo en el estado
  del navegador hasta que recibe su primer medio (ver «La carpeta pendiente»).
- **Un padre puede no tener fila propia.** Si sólo hay medios en
  `"Citem/Diseños"`, la lista devuelve `"Citem/Diseños"` pero no `"Citem"`. La
  UI crea el nodo `Citem` igualmente para colgar la subcarpeta; al abrirlo, la
  lista sale vacía, porque el filtro es exacto.

La columna llega a la base de datos como el resto del esquema: `prisma db push`
al arrancar el contenedor (script `pm2-run` de `package.json`). No hay fichero de
migración. Los medios anteriores a la función tienen `folder = null` y siguen en
la raíz.

---

## Reglas e invariantes

### Todo queda dentro de la organización

Las cuatro operaciones de carpetas (listar, filtrar, mover y renombrar) filtran
por `organizationId`. Mover ids de otra organización no falla: esas filas
simplemente no se actualizan.

### Los medios borrados no cuentan

Listar carpetas, filtrar, mover y renombrar ignoran los medios con `deletedAt`.
Un medio borrado conserva su `folder` antiguo, pero es invisible: no mantiene
viva su carpeta y un renombrado no lo toca.

### El filtro por carpeta es exacto

`GET /media?folder=Citem` devuelve los medios cuyo `folder` es exactamente
`"Citem"`; **no** incluye los de `"Citem/Diseños"`. Ver una marca no muestra el
contenido de sus subcarpetas.

### El renombrado es en cascada, por prefijo

Renombrar `Citem` a `NewBrand` actualiza:

- los medios con `folder = 'Citem'`, que pasan a `'NewBrand'`;
- los medios cuyo `folder` empieza por `'Citem/'`, que pasan a `'NewBrand'`
  seguido del resto de su ruta (`'Citem/Diseños'` → `'NewBrand/Diseños'`,
  a cualquier profundidad).

El prefijo lleva la barra, así que `"Citem2"` no se toca al renombrar `"Citem"`.
Qué carpetas entran se decide en el código, comparando valores (igualdad o
`startsWith` de JavaScript), no con un patrón `LIKE`: un `_` o un `%` en el
nombre es un carácter más, y renombrar `A_B` no alcanza a `AxB/…`. El
`startsWith` de Prisma sí es un `LIKE` sin escapar, así que en la consulta sólo
acota qué filas se leen.

Sólo se sustituye el prefijo: `'Design/Design'` pasa a `'Art/Design'`, no a
`'Art/Art'`. Cada medio se actualiza por su id y sólo si sigue en la carpeta en
que se leyó, así que ninguno se renombra dos veces aunque una ruta nueva
coincida con una vieja (`A` → `A/B` con `A/B` ya existente), y un medio movido
a la vez por otra petición no vuelve atrás. Todas las actualizaciones van en
una transacción: se renombran todas o ninguna.

Ambos nombres se recortan (`trim`) antes de comparar; si quedan iguales, la
operación no hace nada. No se comprueba si el nombre de destino ya existe: si
existe, las dos carpetas se fusionan.

### Subir un medio lo deja en la carpeta que se está viendo

El uploader toma la carpeta activa en el momento en que se añade cada fichero y
la manda con la subida. Si se está en «All media» o en «No folder», no manda nada
y el medio queda en la raíz. En el servidor, `saveFile` recorta el valor y
convierte la cadena vacía en `null`.

Sólo tres caminos de subida aceptan carpeta, uno por proveedor de
almacenamiento del frontend:

| Proveedor | Endpoint | De dónde sale `folder` |
|---|---|---|
| `local` | `POST /media/upload-server` | Campo `folder` del formulario multipart — `@uppy/xhr-upload` manda todos los metadatos del fichero como campos |
| `cloudflare` | `POST /media/:endpoint` con `complete-multipart-upload` | `file.meta.folder` del cuerpo JSON |
| Transloadit | `POST /media/save-media` | Campo `folder` del cuerpo JSON |

Todo lo demás crea medios en la raíz: `POST /media/upload-simple`, la API
pública (`/public/v1/upload` y `/upload-from-url`), las imágenes y los vídeos
generados con IA, lo que llega por `/third-party`, el agente y las herramientas
del chat.

---

## Contrato de la API

Son rutas de la API interna (`MediaController`, prefijo `/media`). La API
pública no tiene endpoints de carpetas.

### `GET /media?page=&search=&folder=`

Lista paginada de medios vivos de la organización, 18 por página, del más
reciente al más antiguo. Responde `{ pages, results }`, y cada resultado incluye
`folder`.

| `folder` | Qué devuelve |
|---|---|
| ausente | Todo, con o sin carpeta |
| `__root__` | Sólo los medios con `folder = null` |
| cualquier otro valor | Sólo los medios con ese `folder` exacto |

`search` se combina con el filtro de carpeta: busca en `originalName`, sin
distinguir mayúsculas.

### `GET /media/folders`

Devuelve un `string[]` con cada valor distinto de `folder` de los medios vivos
de la organización, sin `null`. Es una lista plana de rutas; el árbol lo
construye el cliente.

```json
["Citem", "Citem/Diseños", "Citem/Videos", "Nike"]
```

### `PUT /media/move`

```json
{ "ids": ["…"], "folder": "Citem/Diseños" }
```

`ids` es obligatorio y no puede estar vacío. `folder` es obligatorio: una cadena
o `null`, y `null` devuelve los medios a la raíz. Omitirlo es un 400: el DTO
valida con `@ValidateIf(folder !== null)`, porque `@IsOptional` también dejaría
pasar `undefined`. El valor se guarda tal cual llega, sin recortar. Responde
`{ count }` con las filas actualizadas.

### `PUT /media/rename-folder`

```json
{ "oldName": "Citem", "newName": "NewBrand" }
```

Los dos son cadenas de al menos un carácter y rutas **completas**: para renombrar
la subcarpeta `Diseños` a `Arte`, se manda `"Citem/Diseños"` → `"Citem/Arte"`.
Aplica la cascada descrita arriba. Responde `{ count }` con los medios
renombrados: `0` si los nombres son iguales tras recortarlos o si no hay ningún
medio en esa carpeta. El frontend no lo lee.

### El formato del nombre no se valida

Ni el backend ni el frontend comprueban la forma de la ruta: un nombre puede
contener `/`, terminar en `/` o dejar segmentos vacíos. Quien llame a la API es
responsable de mandar rutas limpias.

---

## El frontend

Todo vive en `MediaBox`, que se usa de dos maneras:

- **La página Medios** (`/media`), con `standalone={true}`. Es la superficie de
  gestión: crear, renombrar y mover.
- **El selector** que abre el editor de publicaciones y los demás consumidores
  (`MultiMediaComponent`, `MediaComponent`, `showMediaBox`, la pantalla de
  desarrollador). Aquí las carpetas sólo sirven para navegar y elegir.

La barra lateral de carpetas está abierta por defecto en los dos modos y se
puede plegar.

### El árbol

`GET /media/folders` llega como lista plana y el componente la convierte en un
árbol de **dos niveles**: el primer segmento de la ruta es la marca y todo lo
demás cuelga directamente de ella, mostrado con su último segmento. Una ruta de
tres niveles, `"A/B/C"`, aparece como `C` bajo `A`.

Arriba del árbol hay dos entradas fijas: **All media** (sin filtro) y **No
folder** (`__root__`). Pulsar un nodo lo abre; pulsar una marca además la
despliega, y su flecha la pliega o despliega sin cambiar de carpeta.

### La carpeta pendiente

Crear una carpeta sólo guarda su ruta en el estado `pendingFolderName` y la
dibuja en el árbol con borde discontinuo. Si se crea con una marca o una
subcarpeta abierta, la nueva cuelga **de la marca** —nunca de la subcarpeta—; si
no, es una marca nueva.

La carpeta se materializa cuando recibe su primer medio, al moverle medios con
«Move to…» o al subirlos mientras está abierta. Mover a la carpeta pendiente
limpia ese estado y la abre. Descartarla (✕) sólo borra el estado local. Como es
estado de React, se pierde al recargar la página.

### Selección, mover y renombrar

Pulsar una miniatura o su casilla alterna **la misma** selección, en la vista de
cuadrícula y en la de lista.

- **En la página Medios** la selección alimenta la barra «Move to…», cuyo
  desplegable ofrece la raíz, la carpeta pendiente y todas las existentes. Se
  vacía al cambiar de carpeta, de búsqueda o de página, para que «Move to…» no
  mueva ficheros que el usuario ya no ve.
- **En el selector** la selección es un carrito: sobrevive a la navegación entre
  carpetas, para poder adjuntar medios de varias. No hay barra de mover, ni
  botones de crear o renombrar.

Renombrar (✎, en la página Medios) pide sólo el último segmento y reconstruye la
ruta completa antes de llamar a `PUT /media/rename-folder`. Si la carpeta abierta
es la renombrada o cuelga de ella, la vista pasa a la ruta nueva. Lo decide
`renamedFolderPath`, la misma función con la que el servidor elige qué renombra:
con `Citem2` abierta, renombrar `Citem` no mueve la vista.

Tras mover o renombrar se revalidan a la vez la lista de medios y la de
carpetas.

### Vistas y zoom

La cuadrícula y la lista usan los mismos datos; la lista añade una columna con la
carpeta (`—` si no tiene) y la cuadrícula la muestra como etiqueta en la
miniatura. El zoom elige el número de columnas de la cuadrícula entre
`[3, 4, 5, 6, 8, 10]` y sólo aparece en esa vista. Ninguno de los dos se guarda:
son preferencias de la sesión y no tocan el backend.

---

## Decisiones de diseño

| Decisión | Por qué |
|---|---|
| Un campo de texto en `Media`, sin tabla `Folder` | No hay estado que mantener sincronizado: la lista de carpetas se deriva de los medios, y una carpeta vacía desaparece sola. El precio es que no pueden existir carpetas vacías en el servidor. |
| La jerarquía como ruta con `/` | Una sola columna basta para cualquier profundidad, y el cliente arma el árbol partiendo la cadena, sin más consultas. |
| `__root__` como valor centinela de `?folder=` | En una query string no se puede distinguir «sin filtro» de «carpeta nula»: parámetro ausente significa todo, `__root__` significa sólo lo que no tiene carpeta. |
| Renombrar con Prisma: un `updateMany` por carpeta afectada, en una transacción | `updateMany` sólo escribe un valor fijo, y cada carpeta tiene su ruta nueva; hay tantas actualizaciones como carpetas distintas, no como medios. La transacción las hace todas o ninguna, sin SQL crudo. |
| Elegir las carpetas en el código, no con `LIKE` | Un `LIKE` convierte `_` y `%` del nombre en comodines y alcanzaría carpetas ajenas (`A_B` casaría con `AxB/…`). Comparar los valores no depende de escapar nada. |
| Sustituir sólo el prefijo | Un `REPLACE` cambiaría todas las apariciones del nombre dentro de la ruta. |
| Filtro exacto por carpeta | Una carpeta muestra lo que tiene dentro y nada más, y la consulta es una igualdad sobre una columna indexada. |
| La carpeta nueva, sólo en el navegador hasta su primer medio | Es la consecuencia directa de no tener tabla: no se escriben filas de relleno para que la carpeta exista. |
| La carpeta de subida se lee de un `ref` | El uploader de Uppy se crea una sola vez (`useMemo` sin dependencias). Leer la carpeta activa de un `ref` en `file-added` evita recrearlo en cada cambio de carpeta. |
| Gestionar sólo en la página Medios | En el selector, seleccionar significa «adjuntar». Una barra de mover ahí empujaría la cuadrícula en cada elección, y crear carpetas sin poder llenarlas sería un callejón sin salida. |
| La selección se vacía en la página Medios y persiste en el selector | En Medios alimenta un movimiento masivo y no debe incluir ficheros que ya no se ven. En el selector es un carrito para adjuntar medios de varias carpetas. |

---

## Dónde vive cada pieza

| Pieza | Fichero |
|---|---|
| Campo `folder` e índice | `libraries/nestjs-libraries/src/database/prisma/schema.prisma` (modelo `Media`) |
| DTO de mover | `libraries/nestjs-libraries/src/dtos/media/move.media.dto.ts` |
| DTO de renombrar y `renamedFolderPath` (a dónde va una ruta al renombrar; la usan el repositorio y la vista) | `libraries/nestjs-libraries/src/dtos/media/rename.folder.dto.ts` |
| Consultas: `getFolders`, `moveMedia`, `renameFolder`, filtro de `getMedia`, saneado en `saveFile` | `libraries/nestjs-libraries/src/database/prisma/media/media.repository.ts` |
| Pruebas de `renameFolder` y de `renamedFolderPath` (`pnpm test`) | `libraries/nestjs-libraries/src/database/prisma/media/media.repository.spec.ts` |
| Servicio (delega en el repositorio) | `libraries/nestjs-libraries/src/database/prisma/media/media.service.ts` |
| Endpoints y lectura de `folder` en las subidas | `apps/backend/src/api/routes/media.controller.ts` |
| `MediaBox`: árbol, carpeta pendiente, selección, mover, renombrar, vistas y zoom | `apps/frontend/src/components/media/media.component.tsx` |
| Página Medios (`standalone`) | `apps/frontend/src/components/new-layout/layout.media.component.tsx` |
| Uploader: sella la carpeta activa en los metadatos del fichero | `apps/frontend/src/components/media/new.uploader.tsx` |
| Plugins de Uppy por proveedor de almacenamiento | `libraries/react-shared-libraries/src/helpers/uppy.upload.ts` |
