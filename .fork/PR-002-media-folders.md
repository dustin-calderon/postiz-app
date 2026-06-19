# PR-002 — `feat(media): virtual folder organization + list/grid view + zoom`

> **Rama upstream (PR limpio):** `feature/media-folders` → upstream `main`
> **Estado:** 🔄 EN ESTABILIZACIÓN — `custom/postiz-dc` (producción) actualizado. PR upstream pendiente de expandir scope.
> **Fecha inicio:** 2026-06-19 | **Fork:** `dustin-calderon/postiz-app`
> **Commit inicial upstream branch:** `eb458a50`
> **Commits en `custom/postiz-dc`:**
> - `cae1892c` — feat: implementación base de carpetas virtuales
> - `99304d78` — fix: audit post-implementación (8 bugs)
> - `5e93f531` — fix: 10 bugs de UX/estado (pendingFolderName, SWR, bulk-move)

> 📘 **Spec técnico detallado:** `.fork/TECH-SPEC-PR-002-media-ux.md` — flujo de datos completo, mapa de archivos, invariantes, tabla de zoom levels.

---

## 1. Contexto

La biblioteca de medios de Postiz no ofrecía ningún mecanismo de organización ni modos de visualización.
Todos los assets vivían en una lista plana paginada, sin filtro por carpeta, sin toggle de layout.

Este PR implementa tres features cohesivas bajo el paraguas de "gestión de media library":

1. **Carpetas virtuales** — campo `folder` (string nullable) en `Media`. Sin tabla nueva. Carpetas inferidas por `DISTINCT`. Footprint de schema mínimo.
2. **Toggle grid / list view** — mismo dataset, dos templates de renderizado. Sin nuevo endpoint, sin nuevo estado de SWR.
3. **Control de zoom (tamaño de tile)** — estado `zoomLevel` que controla el número de columnas del grid (3–10). Sustituye la clase CSS fija `.w8-max` por `style` inline calculado. Solo aplica en vista grid.

---

## 2. Decisiones de diseño

| Decisión | Alternativa considerada | Razón elegida |
|----------|-------------------------|---------------|
| Label string en `Media.folder` | Tabla `Folder` con FK | Cero overhead, sin orphan management |
| Carpetas inferidas via `DISTINCT` | Tabla de gestión separada | Sin estado extra a mantener en sync |
| Sentinel `__root__` en query param | `null` en querystring | URL-safe, sin ambigüedad |
| Rename = `updateMany` en todos los items | Entidad con FK | Consistente con el modelo de borrado (reset a NULL) |
| `NULL` por defecto (root) | String vacío | Semánticamente correcto, compatible con `@@index([folder])` |
| **Carpeta "pendiente" = `pendingFolderName` en estado local** | Crear entrada dummy en DB | Sin escrituras especulativas — la carpeta persiste solo cuando tiene ≥1 item |
| **View mode = estado local `'grid' \| 'list'`** | Persistencia en DB/cookie | Sin round-trip — preferencia de sesión, no dato de negocio |
| **Vista de lista usa el mismo `data` de SWR** | Nuevo endpoint con proyección diferente | Reutiliza datos ya cacheados, cero impacto backend |
| **Zoom = `zoomLevel` int (cols count)** | Clases CSS estáticas tipo `.w4-max`, `.w6-max`... | `style` inline calculado — sin tocar `global.scss`, sin proliferación de clases |
| **`.w8-max` sustituida por `style` inline** | Modificar `global.scss` | `global.scss` es global y compartido — no se debe tocar para features específicas |

**Estructura plana (no jerárquica):** Sin anidamiento padre-hijo deliberadamente.

---

## 3. Arquitectura de carpetas (cómo funcionan realmente)

```
Media (tabla existente)
├── id
├── name
├── path
├── organizationId
├── folder          ← STRING NULLABLE — la única adición al schema
└── ...

GET /media/folders  →  SELECT DISTINCT folder FROM Media
                        WHERE folder IS NOT NULL AND organizationId = X
                        → devuelve [] si nadie ha asignado carpeta aún

Ciclo de vida de una carpeta:
  1. Usuario escribe nombre → setaPendingFolderName() [solo estado React]
  2. Tab aparece en strip con estilo "pendiente" (dashed/semitransparente)
  3. Usuario selecciona items → Move to → [nombre carpeta]
  4. PUT /media/move → UPDATE Media SET folder='X' WHERE id IN (...)
  5. mutateFolders() → SWR refetch → tab pasa a "persistida" (sólido)
  6. setActiveFolder(nombre) → navegación automática
  7. Refresh → carpeta sigue porque hay rows en DB con folder='X'

Borrado de carpeta:
  → No existe endpoint de borrado explícito
  → Mover todos sus items a root (folder=null) → DISTINCT deja de devolver el nombre
  → La carpeta "desaparece" naturalmente
```

---

## 4. Archivos modificados

| Archivo | Tipo | Descripción |
|---------|------|-------------|
| `schema.prisma` | Schema | `folder String?` + `@@index([folder])` en `Media` |
| `move.media.dto.ts` | Nuevo | `{ ids: string[], folder: string \| null }` — `@ValidateIf` para nullable |
| `rename.folder.dto.ts` | Nuevo | `{ oldName: string, newName: string }` — `@IsString @MinLength(1)` |
| `media.repository.ts` | Extendido | `getFolders()`, `moveMedia()`, `renameFolder()`, `getMedia()` con folder filter + guard trim-aware en rename + page coercion fix |
| `media.service.ts` | Extendido | Proxies delgados para los 3 nuevos métodos de repositorio |
| `media.controller.ts` | Extendido | `GET /media/folders`, `PUT /media/move`, `PUT /media/rename-folder` + `?folder=` en `GET /media` |
| `media.component.tsx` | Extendido | Folder UI + view toggle (ver §5) |

---

## 5. Frontend — `MediaBox` (estado actual + pendiente)

### Estado implementado ✅

```
Estado React añadido:
  activeFolder      : string | undefined   — tab activo (undefined = All)
  newFolderName     : string               — input de creación
  creatingFolder    : boolean              — mostrar input vs. botón
  selectedForMove   : string[]             — ids seleccionados para mover
  showMoveMenu      : boolean              — dropdown destino visible
  pendingFolderName : string | null        — carpeta creada, aún sin items en DB

SWR keys:
  ['get-media', page, search, folder]     — grid de media
  'get-media-folders'                     — tab strip de carpetas

loadFolders deps: [fetch]  ← correcto para no tener hook stale
moveToFolder:    mutateFolders() + mutate() en paralelo tras cada move
renameFolderHandler: mutateFolders() + mutate() en paralelo
```

```
UI implementada:
  [All] [No folder] [📁 Camp...] [✎] [...] [+ New folder]
         ↑ tab strip con rename en hover

  Banner amarillo ← pendingFolderName activo (guía al usuario)
  Checkboxes en group-hover (top-left de cada thumbnail)
  Bulk-move bar (aparece cuando selectedForMove.length > 0)
  Badge de carpeta en thumbnail (top-right, truncado 80px)
  Dropdown Move-to: root + pendingFolder (✨) + folders persistidas
```

### Pendiente de implementar 🔲

#### A. Tab pendiente visible en el strip

```
[All] [No folder] [📁 Citam] [✨ NuevaCarpeta] [+ New folder]
                              ↑ dashed border, opacity-60
                              Al hacer click → empty state con instrucciones
                              (no navega a grid vacío sin contexto)
```

Implementación:
- Insertar el tab `pendingFolderName` entre las carpetas persistidas y el `+ New folder`
- Estilo: `border-dashed border-[#612BD3]/50 opacity-70` cuando no activo, `bg-[#612BD3] opacity-100` cuando activo
- Al navegar a él: empty state contextual ("Selecciona items y muévelos aquí")
- Botón "Descartar" en el tab (✕ pequeño) → `setPendingFolderName(null)`
- Eliminar el banner amarillo actual (redundante con el tab visible)

#### B. Toggle Grid / List view

```
Controles nuevos en la barra superior (junto a "+ Subir"):
  [⊞ Grid]  [≡ List]  — toggle con iconos SVG nativos (sin dependencia extra)

Estado nuevo:
  viewMode : 'grid' | 'list'   — useState local, valor inicial 'grid'

Vista Grid (actual):
  grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))]
  thumbnails cuadrados con overlay de nombre

Vista List:
  tabla o flex-col con filas de 44px altura
  columnas: thumbnail 40×40 | nombre | carpeta | tipo | tamaño | fecha
  acción: checkbox + delete en la fila (misma lógica que en grid)
  sin scroll horizontal — columnas se colapsan en mobile

Implementación:
  - El mismo `data.results` del SWR existente se reutiliza en ambas vistas
  - El checkbox de selección para move aparece en la fila (column 0)
  - Badge de carpeta → columna "Carpeta" en list view
  - Sin cambios de backend — es renderizado alternativo del mismo payload
```

#### C. Impacto en el flujo completo con ambas features

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ [All] [No folder] [📁 Campaigns] [✨ Citam] [+ New folder]                   │
│ [Search..........................]  [⊞][≡]  [−]──●──[+]  [+ Subir]          │
│─────────────────────────────────────────────────────────────────────────────│
│ Vista Grid (zoom=4 cols):          │ Vista List:                              │
│ ┌──────────┐ ┌──────────┐         │ ☐ 🖼 img.png      Campaigns  img         │
│ │ ☐  img   │ │ ☐  img   │         │ ☐ 🎬 video.mp4    —          vid         │
│ │          │ │          │         │ ☐ 🖼 logo.svg     Citam       img         │
│ └──────────┘ └──────────┘         │                                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. API contract (sin cambios respecto al diseño inicial)

### `GET /media?folder=<value>`

| Valor | Comportamiento |
|-------|----------------|
| Omitido | Todo el catálogo (backwards compatible) |
| `__root__` | Solo items sin carpeta asignada (`folder IS NULL`) |
| `<nombre>` | Solo items en esa carpeta (`folder = nombre`) |

### `GET /media/folders` → `["Campaigns", "Clients", "Q2-2026"]`

### `PUT /media/move` → `{ ids: string[], folder: string | null }`

### `PUT /media/rename-folder` → `{ oldName: string, newName: string }`

> `renameFolder` tiene guard trim-aware: si `oldName.trim() === newName.trim()` → no-op.
> `moveMedia` usa `@ValidateIf` (no `@IsOptional`) para aceptar `folder: null` correctamente.

---

## 7. Backwards compatibility

- Todo el media existente tiene `folder = NULL` (root) — **sin migración de datos**
- `GET /media` sin `?folder=` devuelve todo el catálogo — **comportamiento anterior intacto**
- `prisma-db-push` aplicado en producción Beelink — columna existe en DB ✅
- `@@index([folder])` en schema — consultas `DISTINCT` eficientes ✅

---

## 8. Checklist

### Backend ✅ completo
- [x] Schema: `folder String?` + `@@index([folder])`
- [x] DTOs: `move.media.dto.ts` + `rename.folder.dto.ts` con validación correcta
- [x] Repository: `getFolders`, `moveMedia`, `renameFolder` + filter en `getMedia`
- [x] Repository: guard rename trim-aware + page coercion fix (`Number(page) > 0`)
- [x] Service: proxies delgados
- [x] Controller: 3 endpoints + `?folder=` — sin conflicto de rutas (registradas antes que `/:id`)
- [x] Prisma Client regenerado — tipos explícitos, cero errores TS en archivos modificados

### Frontend — carpetas ✅ completo
- [x] Estado: `activeFolder`, `pendingFolderName`, `selectedForMove`, `showMoveMenu`
- [x] SWR: `mutateFolders()` + `mutate()` en paralelo tras move y rename
- [x] `loadFolders` con `fetch` en deps (sin hook stale)
- [x] Checkbox en `group-hover`, `opacity-0 → opacity-100`
- [x] Bulk-move bar: `flex-wrap w-full` (responsive), `boolean` toggle correcto
- [x] Rename: error handling + toast + `mutate()` para badge actualización
- [x] Move: error handling + `console.error` (no catch silencioso)
- [x] Badge de carpeta en thumbnail
- [x] Dropdown Move-to: root + pendingFolder (✨) + persistidas

### Frontend — pendiente 🔲
- [ ] Tab pendiente visible en strip (dashed, empty state contextual, botón `✕` discard)
- [ ] Eliminar banner amarillo (sustituido por el tab visible)
- [ ] Toggle grid/list view (`viewMode` state + ListView template)
- [ ] Empty state específico al navegar a tab pendiente
- [ ] Zoom: estado `zoomLevel`, constante `ZOOM_LEVELS`, slider + botones `−`/`+`
- [ ] Zoom: sustituir `w8-max` en tiles y skeletons por `style` inline
- [ ] Zoom: ocultar controles en `viewMode === 'list'`

### Deployment
- [x] `prisma-db-push` ejecutado en Beelink — columna `folder` confirmada en `\d "Media"`
- [x] Build `5e93f531` desplegado — container `postiz` healthy
- [ ] Validación manual completa en producción tras implementar A + B
- [ ] Actualizar rama `feature/media-folders` con los cambios adicionales para upstream PR

---

## 9. Historia de commits

```
custom/postiz-dc (producción):
  5e93f531  fix(media): remediate 10 bugs in virtual folder UX
  99304d78  fix(media-folders): audit — remediate 8 bugs post-implementation
  d0ea38fe  docs(.fork): add PR-002 doc + STRATEGY sync protocol
  cae1892c  feat(media): add virtual folder organization  ← base

feature/media-folders (rama limpia upstream PR):
  eb458a50  feat(media): add virtual folder organization
  ↑ pendiente de actualizar con fixes + nuevas features antes de expandir PR
```

---

## 10. Próximos pasos (orden de ejecución)

1. Implementar **tab pendiente** en el strip — eliminar banner amarillo
2. Implementar **toggle grid/list** — nuevo `viewMode` state + template list
3. Commit en `custom/postiz-dc` + build en Beelink
4. Validación manual completa en producción
5. Cherry-pick de los cambios a `feature/media-folders` (rama limpia) para expandir el upstream PR

---

*Documento actualizado: 2026-06-19. Scope ampliado: tab pendiente visible + toggle grid/list.*
