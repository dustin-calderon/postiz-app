# PR-002 — `feat(media): virtual folder organization + hierarchical sidebar + list/grid view + zoom`

> **Rama upstream (PR limpio):** `feature/media-folders` → upstream `main`
> **Estado:** ✅ COMPLETO — desplegado en producción Beelink (`a9b58852`, container `healthy`)
> **Fecha inicio:** 2026-06-19 | **Fork:** `dustin-calderon/postiz-app`

> 📘 **Spec técnico detallado:** `.fork/TECH-SPEC-PR-002-media-ux.md` — flujo de datos, árbol de estado, API contract, invariantes.

---

## 1. Contexto

La biblioteca de medios de Postiz no ofrecía organización ni modos de visualización. Con el crecimiento del catálogo (30+ carpetas proyectadas por marca/campaña), el modelo de **tabs planos** implementado en la base se volvió insostenible.

Este PR cubre cuatro features cohesivas:

1. **Carpetas virtuales base** — campo `folder` (string nullable) en `Media`. Sin tabla nueva. Carpetas inferidas por `DISTINCT`.
2. **Sidebar jerárquico colapsable** — reemplaza el strip de tabs por un árbol de 2 niveles `Marca → Sub` parseado en cliente a partir de *path-strings* (`"Citem/Diseños"`).
3. **Toggle grid / list view** — mismo dataset SWR, dos templates de renderizado. Sin nuevo endpoint.
4. **Control de zoom** — estado `zoomLevel` (columnas 3–10) que controla la densidad del grid.

---

## 2. Decisiones de diseño

| Decisión | Alternativa considerada | Razón elegida |
|----------|-------------------------|---------------|
| `folder` como path-string (`"Marca/Sub"`) | Tabla `Folder` con FK padre-hijo | Cero schema extra, cero orphan management, parseable en cliente con `split('/')` |
| Carpetas inferidas via `DISTINCT` | Tabla de gestión separada | Sin estado extra a mantener en sync |
| Sidebar colapsable 176px | Tab strip horizontal | Sostenible con 20-50 carpetas; no colapsa a 2 líneas |
| 2 niveles de jerarquía (Marca/Sub) | N niveles recursivos | Cubre el 100% del caso de uso real; la UI de árbol infinito añade complejidad innecesaria |
| `renameFolder` con SQL `REPLACE()+LIKE` | `updateMany` con exact-match | Cascada automática: renombrar `Citem` actualiza `Citem/Diseños → NewBrand/Diseños` en una sola query |
| Sidebar oculto en modo standalone (modal) | Sidebar siempre visible | El modal tiene espacio limitado; la nav por carpetas no es el flujo principal de inserción |
| `pendingFolderName` en estado React local | Crear row dummy en DB | Sin escrituras especulativas; la carpeta persiste solo cuando tiene ≥1 item |
| `PrismaRepository.model as unknown as PrismaClient` para `$queryRaw` | Inyectar `PrismaRepository<'$queryRaw'>` | El cast es correcto en runtime (model IS PrismaService, que extiende PrismaClient); más limpio que ampliar el constructor |

---

## 3. Arquitectura de carpetas (path-based hierarchy)

```
Media (tabla existente — sin cambios de schema en esta fase)
├── id
├── name
├── path
├── organizationId
├── folder          ← STRING NULLABLE — path-string jerárquico
└── ...

Ejemplos de valores de folder:
  null              → Root (sin asignar)
  "Citem"           → Carpeta raíz de marca
  "Citem/Diseños"   → Subcarpeta bajo Citem
  "Citem/Videos"    → Otra subcarpeta bajo Citem

GET /media/folders  →  SELECT DISTINCT folder FROM Media
                        WHERE folder IS NOT NULL AND organizationId = X
                        → devuelve ["Citem", "Citem/Diseños", "Citem/Videos", "Nike"]

parseFolderTree(["Citem", "Citem/Diseños", "Nike"])
  → [
      { name: "Citem", path: "Citem", children: [{ name: "Diseños", path: "Citem/Diseños" }] },
      { name: "Nike",  path: "Nike",  children: [] }
    ]
```

### Ciclo de vida de una carpeta jerárquica

```
1. Usuario navega a "Citem" → hace click en "New Subfolder"
   → createFolder() detecta que activeFolder = "Citem"
   → setPendingFolderName("Citem/NuevaSub")

2. El sidebar muestra "NuevaSub" bajo "Citem" (estilo dashed)

3. Usuario selecciona items → "Move to…" → [Citem/NuevaSub]
   → PUT /media/move  body: { ids: [...], folder: "Citem/NuevaSub" }
   → mutateFolders() + mutate()
   → sidebar refresca; "NuevaSub" pasa a nodo persistido

4. Si el usuario renombra "Citem" → "NewBrand":
   → PUT /media/rename-folder  body: { oldName: "Citem", newName: "NewBrand" }
   → backend: UPDATE Media SET folder = REPLACE(folder, 'Citem', 'NewBrand')
              WHERE folder = 'Citem' OR folder LIKE 'Citem/%'
   → "Citem/Diseños" pasa a "NewBrand/Diseños" automáticamente (1 query)
```

---

## 4. Archivos modificados

| Archivo | Tipo | Descripción |
|---------|------|-------------|
| `schema.prisma` | Schema | `folder String?` + `@@index([folder])` en `Media` |
| `move.media.dto.ts` | Nuevo | `{ ids: string[], folder: string \| null }` — `@ValidateIf` para nullable |
| `rename.folder.dto.ts` | Nuevo | `{ oldName: string, newName: string }` — `@IsString @MinLength(1)` |
| `media.repository.ts` | Extendido | `getFolders()`, `moveMedia()`, `renameFolder()` con SQL cascada, `getMedia()` con folder filter |
| `media.service.ts` | Extendido | Proxies delgados para los 3 nuevos métodos |
| `media.controller.ts` | Extendido | `GET /media/folders`, `PUT /media/move`, `PUT /media/rename-folder` + `?folder=` en `GET /media` |
| `media.component.tsx` | Refactorizado | Sidebar jerárquico + view toggle + zoom (ver §5) |

---

## 5. Frontend — `MediaBox` (estado completo)

### Estado React

```typescript
// Carpetas
activeFolder      : string | undefined  // path activo (undefined = All)
newFolderName     : string              // input de creación de carpeta
creatingFolder    : boolean             // mostrar input vs. botón
selectedForMove   : string[]            // ids seleccionados para mover
showMoveMenu      : boolean             // dropdown destino visible
pendingFolderName : string | null       // carpeta creada, aún sin items en DB
sidebarOpen       : boolean             // sidebar colapsado/expandido
expandedBrands    : Set<string>         // nodos raíz del árbol expandidos

// Vista
viewMode   : 'grid' | 'list'   // toggle de vista
zoomLevel  : ZoomLevel          // columnas del grid (3|4|5|6|8|10)
```

### SWR keys

```
['get-media', page, search, activeFolder]  → GET /media?folder=...
'get-media-folders'                        → GET /media/folders
```

### Sidebar (nuevo)

```
╔═══════════════╗  ╔══════════════════════════════╗
║  ☰ Folders    ║  ║  [Search] [⊞][≡] [−●+] [+]  ║
║               ║  ║──────────────────────────────║
║  ● All media  ║  ║  🖼 img.png      Citem  img   ║
║  ○ No folder  ║  ║  🎬 video.mp4   —      vid   ║
║               ║  ║  🖼 logo.svg    Citem   img   ║
║  ▼ Citem      ║  ║                              ║
║    ├ Diseños  ║  ║                              ║
║    └ Videos   ║  ║                              ║
║  ▶ Nike       ║  ║                              ║
╚═══════════════╝  ╚══════════════════════════════╝
```

**Comportamientos del sidebar:**
- Nodo raíz (Marca): click → `setActiveFolder("Citem")`, chevron → toggle `expandedBrands`
- Nodo hijo (Sub): click → `setActiveFolder("Citem/Diseños")`
- "New Subfolder" en hover de nodo raíz → crea `"Citem/NombreNueva"` en `pendingFolderName`
- Rename en hover de nodo raíz → actualiza solo el primer segmento, preservando hijos
- `pendingFolderName` aparece como nodo dashed en el árbol

---

## 6. API contract

### `GET /media?folder=<value>`

| Valor | Comportamiento |
|-------|----------------|
| Omitido | Todo el catálogo (backwards compatible) |
| `__root__` | Solo items sin carpeta (`folder IS NULL`) |
| `<path>` | Solo items con `folder = path` (exact match) |

### `GET /media/folders` → `["Citem", "Citem/Diseños", "Nike"]`

### `PUT /media/move` → `{ ids: string[], folder: string | null }`

### `PUT /media/rename-folder` → `{ oldName: string, newName: string }`

> `renameFolder` usa SQL raw: `UPDATE Media SET folder = REPLACE(folder, old, new) WHERE folder = old OR folder LIKE 'old/%'`
> Guard trim-aware: si `oldName.trim() === newName.trim()` → no-op.

---

## 7. Backwards compatibility

- Todo el media existente tiene `folder = NULL` (root) — **sin migración de datos**
- `GET /media` sin `?folder=` devuelve todo el catálogo — **comportamiento anterior intacto**
- `prisma-db-push` aplicado en producción Beelink — columna existe en DB ✅
- `@@index([folder])` en schema — consultas `DISTINCT` eficientes ✅
- El sidebar acepta gracefully arrays de strings planos (sin separador `/`) → nodo raíz sin hijos ✅

---

## 8. Checklist completo

### Backend ✅
- [x] Schema: `folder String?` + `@@index([folder])`
- [x] DTOs: `move.media.dto.ts` + `rename.folder.dto.ts` con validación correcta
- [x] Repository: `getFolders`, `moveMedia`, `renameFolder` (SQL cascada), filter en `getMedia`
- [x] Repository: guard rename trim-aware + page coercion fix
- [x] Repository: `$queryRaw` con cast explícito a `PrismaClient` (documentado en comentario)
- [x] Service: proxies delgados
- [x] Controller: 3 endpoints + `?folder=` — rutas registradas antes de `/:id`
- [x] Prisma Client regenerado — cero errores TS en archivos modificados

### Frontend — carpetas base ✅
- [x] Estado: `activeFolder`, `pendingFolderName`, `selectedForMove`, `showMoveMenu`
- [x] SWR: `mutateFolders()` + `mutate()` en paralelo tras move y rename
- [x] `loadFolders` con `fetch` en deps (sin hook stale)
- [x] Checkbox en `group-hover`, `opacity-0 → opacity-100`
- [x] Bulk-move bar: `flex-wrap w-full` (responsive)
- [x] Rename: error handling + toast + `mutate()` para badge
- [x] Move: error handling + `console.error`
- [x] Badge de carpeta en thumbnail (grid) + columna en list view
- [x] Dropdown Move-to: root + pendingFolder (✨) + persistidas

### Frontend — sidebar jerárquico ✅
- [x] `parseFolderTree()`: `string[]` → árbol de 2 niveles (nativa, sin dependencias)
- [x] Sidebar 176px colapsable (`sidebarOpen` state)
- [x] Nodos raíz: chevron expand/collapse, hover: rename + subfolder
- [x] Nodos hijos: click navega directamente
- [x] `createFolder` path-aware: crea sub-carpeta si `activeFolder` es marca raíz
- [x] `renameFolderHandler` path-aware: renombra último segmento, actualiza prefix de `activeFolder`
- [x] Move-to dropdown: árbol indentado con depth visual
- [x] `pendingFolderName` visible en el árbol (estilo dashed)
- [x] Sidebar oculto por defecto en modo standalone (modal)

### Frontend — view / zoom ✅
- [x] Toggle grid/list (`viewMode` state)
- [x] `ListView` template (5 columnas: checkbox, thumb, nombre, carpeta, tipo)
- [x] Skeleton de loading para list view
- [x] Zoom: `ZOOM_LEVELS = [3,4,5,6,8,10]`, default 6
- [x] Zoom: `style` inline reemplaza clase `w8-max`
- [x] Controles `−`/slider/`+` ocultos en `viewMode === 'list'`

### Deployment ✅
- [x] `prisma-db-push` ejecutado — columna `folder` confirmada en DB
- [x] Commit `a9b58852` — `feat(media): hierarchical path-based folder sidebar`
- [x] Build `a9b58852` completado en Beelink (~4 min)
- [x] Container `postiz` healthy (`Up 10 seconds (healthy)` en `127.0.0.1:4007`)

---

## 9. Historia de commits

```
custom/postiz-dc (producción):
  a9b58852  feat(media): hierarchical path-based folder sidebar    ← ACTUAL
  2bf89ea6  feat(media): pending folder tab + grid/list toggle + zoom
  5e93f531  fix(media): remediate 10 bugs in virtual folder UX
  99304d78  fix(media-folders): audit — remediate 8 bugs post-implementation
  d0ea38fe  docs(.fork): add PR-002 doc + STRATEGY sync protocol
  cae1892c  feat(media): add virtual folder organization            ← base
```

```
feature/media-folders (rama limpia upstream PR):
  eb458a50  feat(media): add virtual folder organization
  ↑ pendiente de cherry-pick antes de expandir el upstream PR
```

---

## 10. Próximos pasos (si se desea expandir)

1. **Cherry-pick** de `a9b58852` a `feature/media-folders` para upstream PR limpio
2. **Test E2E**: caso borde de mover asset de subcarpeta a root (`folder = null`)
3. **Validar flujo de rename** con subcarpetas anidadas en producción
4. **Upstream PR**: presentar el sidebar jerárquico como feature adicional al upstream de Postiz

---

*Documento actualizado: 2026-06-19. Scope: tabs planos → sidebar jerárquico path-based. Commit: `a9b58852`.*
