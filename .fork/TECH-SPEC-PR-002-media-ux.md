# TECH-SPEC — Media Library UX: Folders Tab + List View + Zoom Control

> **Asociado a:** PR-002 (`feat(media): virtual folder organization + list/grid view + zoom`)
> **Rama:** `custom/postiz-dc` (producción) / `feature/media-folders` (upstream PR)
> **Última actualización:** 2026-06-19

---

## 1. Contexto y motivación

### El problema original

La biblioteca de medios de Postiz (`/media`) presentaba tres carencias funcionales:

1. **Sin organización:** todos los assets en una lista plana sin filtros — inmanejable con >50 archivos.
2. **Sin modos de vista:** el grid de 6 columnas fijas es la única opción — no hay densidad ajustable.
3. **Sin zoom:** el tamaño de thumbnail es fijo (`w8-max = calc(100% / 6)`) — no permite ver más o menos en pantalla.

### La solución

Tres mejoras cohesivas bajo el paraguas "gestión de media library":

| Feature | Complejidad | Backend | Frontend |
|---------|-------------|---------|----------|
| A. Tab de carpeta pendiente visible | Mínima | ❌ sin cambios | ✅ solo JSX |
| B. Toggle Grid / List view | Baja | ❌ sin cambios | ✅ estado + template |
| C. Control de zoom (tamaño de tile) | Mínima | ❌ sin cambios | ✅ estado + CSS inline |

---

## 2. Mapa de archivos involucrados

### Frontend (único layer afectado por las features A, B, C)

```
apps/frontend/src/
├── components/media/
│   └── media.component.tsx          ← ARCHIVO PRINCIPAL — toda la UI de MediaBox
├── app/
│   └── global.scss                  ← Define .w8-max (clase CSS del grid actual)
└── (ningún otro archivo de frontend)
```

### Backend (implementado en PR-002 base, sin cambios adicionales)

```
apps/backend/src/api/routes/
└── media.controller.ts              ← endpoints /media/folders, /media/move, /media/rename-folder

libraries/nestjs-libraries/src/
├── database/prisma/
│   ├── schema.prisma                ← Media.folder String? + @@index([folder])
│   └── media/
│       ├── media.repository.ts      ← getFolders(), moveMedia(), renameFolder(), getMedia()
│       └── media.service.ts         ← proxies delgados de repositorio
└── dtos/media/
    ├── move.media.dto.ts            ← { ids: string[], folder: string | null }
    └── rename.folder.dto.ts         ← { oldName: string, newName: string }
```

---

## 3. Flujo de datos completo (estado actual, post-PR-002-base)

### 3.1 Carga de media

```
MediaBox mount
  │
  ├─ loadMedia() → GET /media?page=N[&search=S][&folder=F]
  │    ↑ deps: [page, debouncedSearch, activeFolder]
  │    ↓ SWR key: ['get-media', page, search, folder]
  │    ↓ respuesta: { results: Media[], pages: number }
  │
  └─ loadFolders() → GET /media/folders
       ↑ deps: [fetch]
       ↓ SWR key: 'get-media-folders'
       ↓ respuesta: string[]  — ej: ["Campaigns", "Clientes", "Q2-2026"]
```

### 3.2 Creación de carpeta (flujo pendiente actual)

```
Usuario escribe nombre → Enter / click "Create"
  │
  ├─ setCreatingFolder(false)
  ├─ setNewFolderName('')
  └─ setPendingFolderName(nombre)   ← SIN llamada API — solo estado React

  Resultado: banner amarillo visible, NINGÚN tab nuevo en el strip
```

### 3.3 Mover items a carpeta

```
Usuario activa checkboxes → selectedForMove = ['id1', 'id2']
  │
  ├─ showMoveMenu toggle → dropdown con: [root, ✨ pendingFolder, ...folders persistidas]
  │
  └─ moveToFolder(ids, folder) → PUT /media/move
        body: { ids: string[], folder: string | null }
        └─ onSuccess:
             ├─ mutateFolders()   → invalida SWR 'get-media-folders' → GET /media/folders
             ├─ mutate()          → invalida SWR ['get-media', ...]   → GET /media?...
             ├─ setSelectedForMove([])
             ├─ setShowMoveMenu(false)
             └─ si folder === pendingFolderName:
                  ├─ setPendingFolderName(null)   ← carpeta ya persistida
                  └─ setActiveFolder(folder)      ← navega al nuevo tab
```

### 3.4 API endpoints de media

| Método | Ruta | Descripción | Parámetros |
|--------|------|-------------|------------|
| `GET` | `/media` | Lista media paginada | `?page, ?search, ?folder` |
| `GET` | `/media/folders` | Lista carpetas existentes | — |
| `PUT` | `/media/move` | Mueve items a carpeta | body: `MoveMediaDto` |
| `PUT` | `/media/rename-folder` | Renombra carpeta | body: `RenameFolderDto` |
| `POST`| `/media` | Sube archivo nuevo | multipart/form-data |
| `DELETE` | `/media/:id` | Elimina archivo | — |

> ⚠️ El orden de registro en `media.controller.ts` es crítico:
> `GET /media/folders` y `PUT /media/move` deben estar registrados **antes** de `GET /media/:id`
> para evitar que Express interprete `folders` como un `:id` wildcard.

---

## 4. Feature A — Tab de carpeta pendiente visible en el strip

### 4.1 Problema actual

Al crear una carpeta nueva, el `pendingFolderName` solo genera un banner amarillo.
El tab de la carpeta **no aparece en el strip** hasta que tiene ≥1 item en DB.
Esto viola la expectativa del usuario: "creé la carpeta, ¿dónde está?".

### 4.2 Solución

Renderizar el tab del `pendingFolderName` directamente en el strip con estilo diferenciado:

```
[All] [No folder] [📁 Campaigns] [✨ NuevaCarpeta] [+ New folder]
                                   ↑ dashed, opacity-70
```

**Comportamiento del tab pendiente:**
- Estilo: `border border-dashed border-[#612BD3]/60 opacity-70` (no activo)
- Estilo activo: `bg-[#612BD3] text-white opacity-100` (al hacer click sobre él)
- Botón `✕` pequeño en el tab → `setPendingFolderName(null)` (descartar)
- Al navegar a él (`setActiveFolder(pendingFolderName)`): empty state contextual
- Cuando `moveToFolder` persiste el primer item → `setPendingFolderName(null)` → tab pasa a ser "normal" (aparecerá como persistido tras `mutateFolders()`)

### 4.3 Empty state del tab pendiente

```tsx
// Mostrar cuando: activeFolder === pendingFolderName && !data?.results?.length
<div className="flex flex-col items-center gap-[12px] text-center p-[40px]">
  <FolderIcon size={48} className="opacity-30" />
  <p className="text-[16px] font-[600]">Esta carpeta está vacía</p>
  <p className="text-[13px] text-textColor/60">
    Selecciona archivos con los checkboxes y usa "Move to…" para añadirlos aquí.
  </p>
</div>
```

### 4.4 Eliminar banner amarillo

El banner amarillo actual es redundante con el tab visible. Se elimina.
El estado `pendingFolderName` se mantiene — solo cambia su presentación.

### 4.5 Código afectado

- **Archivo:** `media.component.tsx`
- **Zona:** Sección del tab strip (líneas ~539–595 actuales)
- **Cambio:** insertar `{pendingFolderName && <TabPending />}` antes del botón `+ New folder`
- **Cambio:** eliminar el bloque del banner amarillo

---

## 5. Feature B — Toggle Grid / List view

### 5.1 Estado nuevo

```typescript
type ViewMode = 'grid' | 'list';
const [viewMode, setViewMode] = useState<ViewMode>('grid');
```

Sin persistencia backend ni localStorage. Es preferencia de sesión, no dato de negocio.

### 5.2 Controles de toggle

Añadidos en la barra superior, a la izquierda del botón "+ Subir":

```tsx
<div className="flex items-center gap-[2px] rounded-[6px] border border-newColColor overflow-hidden">
  <button
    onClick={() => setViewMode('grid')}
    className={clsx('px-[8px] h-[30px] text-[14px]', viewMode === 'grid' && 'bg-[#612BD3] text-white')}
    title="Vista de cuadrícula"
  >
    ⊞
  </button>
  <button
    onClick={() => setViewMode('list')}
    className={clsx('px-[8px] h-[30px] text-[14px]', viewMode === 'list' && 'bg-[#612BD3] text-white')}
    title="Vista de lista"
  >
    ≡
  </button>
</div>
```

### 5.3 Vista Grid (existente, sin cambios)

Clase CSS actual: `w8-max` (`width: calc(100% / 6)`) + `aspect-square` + `float: left`.
La feature C (zoom) modifica el divisor de columnas dinámicamente.

### 5.4 Vista List

Mismo `data.results` del SWR. Template alternativo:

```tsx
// Contenedor: reemplaza el div float con flex-col
<div className="flex flex-col w-full divide-y divide-newColColor/30">
  {data?.results.map((media) => (
    <div className="flex items-center gap-[12px] h-[52px] px-[8px] hover:bg-newColColor/10 group">
      {/* Columna 0: checkbox selección move */}
      <input type="checkbox" checked={...} onChange={...} className="w-[14px] h-[14px] accent-[#612BD3]" />
      {/* Columna 1: thumbnail 40×40 */}
      <div className="w-[40px] h-[40px] rounded-[4px] overflow-hidden flex-shrink-0">
        {isVideo ? <VideoFrame url={...} /> : <img src={...} className="w-full h-full object-cover" />}
      </div>
      {/* Columna 2: nombre (ocupa espacio disponible) */}
      <span className="flex-1 text-[13px] truncate">{media.originalName}</span>
      {/* Columna 3: carpeta */}
      <span className="w-[100px] text-[12px] text-textColor/60 truncate">{media.folder ?? '—'}</span>
      {/* Columna 4: tipo inferido */}
      <span className="w-[40px] text-[11px] text-textColor/50 uppercase">
        {hasExtension(media.path, 'mp4') ? 'video' : 'img'}
      </span>
      {/* Columna 5: acciones en hover */}
      <button onClick={deleteImage(media)} className="hidden group-hover:block text-red-400">✕</button>
    </div>
  ))}
</div>
```

**Invariantes de la vista list:**
- El mecanismo "select for insert" (borde morado, número de orden) NO aplica en list view — solo aplica en modo standalone/modal.
- El `selectedForMove` (checkbox de carpeta) SÍ aplica y funciona igual.
- Click en la fila → `addRemoveSelected(media)` si `!standalone`.
- Sin scroll horizontal — columnas se colapsan en viewports pequeños con `truncate`.

---

## 6. Feature C — Control de zoom (tamaño de tile)

### 6.1 Cómo funciona el grid actual

```scss
/* global.scss — línea 800 */
.w8-max {
  width: calc(100% / 6);      /* 6 columnas fijas */
  max-width: calc(100% / 6);
}
```

Cada tile es `1/6` del ancho del contenedor, con `aspect-square` para mantener la proporción.
El grid usa `float: left` — no es CSS Grid ni Flexbox.

### 6.2 Estrategia de zoom

**No modificar `global.scss`**. En su lugar, sustituir la clase `w8-max` por una anchura
calculada en línea a partir de un estado `zoomLevel`:

```typescript
const ZOOM_LEVELS = [3, 4, 5, 6, 8, 10] as const;
type ZoomLevel = typeof ZOOM_LEVELS[number];
const [zoomLevel, setZoomLevel] = useState<ZoomLevel>(6); // default = 6 cols (actual)
```

El valor de `zoomLevel` representa el **número de columnas** visibles.

```tsx
// Estilo inline en el div de cada tile (reemplaza w8-max):
style={{ width: `calc(100% / ${zoomLevel})`, maxWidth: `calc(100% / ${zoomLevel})` }}
className="group px-[3px] py-[3px] float-left rounded-[6px] aspect-square"
```

### 6.3 Controles de zoom

Slider + botones de `-` y `+`, en la barra superior junto al toggle de vista:

```
[⊞][≡]  [−] ────●──── [+]
         ↑ zoom slider
```

```tsx
<div className="flex items-center gap-[6px]">
  <button
    onClick={() => setZoomLevel(prev => {
      const idx = ZOOM_LEVELS.indexOf(prev);
      return ZOOM_LEVELS[Math.max(0, idx - 1)];
    })}
    disabled={zoomLevel === ZOOM_LEVELS[0]}
    className="px-[6px] h-[30px] rounded-[6px] bg-newColColor disabled:opacity-30"
    title="Menos archivos, más grandes"
  >−</button>
  <input
    type="range"
    min={0}
    max={ZOOM_LEVELS.length - 1}
    value={ZOOM_LEVELS.indexOf(zoomLevel)}
    onChange={(e) => setZoomLevel(ZOOM_LEVELS[Number(e.target.value)])}
    className="w-[80px] accent-[#612BD3]"
  />
  <button
    onClick={() => setZoomLevel(prev => {
      const idx = ZOOM_LEVELS.indexOf(prev);
      return ZOOM_LEVELS[Math.min(ZOOM_LEVELS.length - 1, idx + 1)];
    })}
    disabled={zoomLevel === ZOOM_LEVELS[ZOOM_LEVELS.length - 1]}
    className="px-[6px] h-[30px] rounded-[6px] bg-newColColor disabled:opacity-30"
    title="Más archivos, más pequeños"
  >+</button>
</div>
```

### 6.4 Tabla de niveles de zoom

| Index | Cols | Tile aprox (en 1200px) | Caso de uso |
|-------|------|------------------------|-------------|
| 0 | 3 | 400px | Ver detalles grandes |
| 1 | 4 | 300px | Thumbnails cómodos |
| 2 | 5 | 240px | Balance |
| 3 | 6 | 200px | **Default actual** |
| 4 | 8 | 150px | Muchos archivos |
| 5 | 10 | 120px | Density máxima |

### 6.5 El zoom solo aplica en vista Grid

En vista List el zoom no tiene sentido (filas de altura fija).
Los controles de zoom se muestran condicionalmente: `{viewMode === 'grid' && <ZoomControls />}`.

---

## 7. Interacción entre las tres features

### 7.1 Barra de controles unificada

La barra superior de la media library queda:

```
[All] [No folder] [📁 Campaigns] [✨ NuevaCarpeta] [+ New folder]
─────────────────────────────────────────────────────────────────
[Search..............................]  [⊞][≡]  [−]──●──[+]  [+ Subir]
                                        ↑ view  ↑ zoom (grid only)
```

### 7.2 Estado combinado

```typescript
// Nuevos estados añadidos al MediaBox
const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
const [zoomLevel, setZoomLevel] = useState<ZoomLevel>(6);
// Estados existentes — sin modificar:
// activeFolder, pendingFolderName, selectedForMove, showMoveMenu, ...
```

### 7.3 Lógica de renderizado condicional

```tsx
{/* Zona de contenido principal */}
{viewMode === 'grid' ? (
  <GridView
    data={data}
    zoomLevel={zoomLevel}
    selectedForMove={selectedForMove}
    // ... resto de props
  />
) : (
  <ListView
    data={data}
    selectedForMove={selectedForMove}
    // ... resto de props
  />
)}
```

Ambas vistas reciben el mismo `data` del SWR — **cero llamadas API adicionales**.

---

## 8. Skeleton / loading states

### Grid loading (actual)

```tsx
{isLoading && [...new Array(16)].map((_, i) => (
  <div style={{ width: `calc(100% / ${zoomLevel})`, maxWidth: `calc(100% / ${zoomLevel})` }}
       className="px-[3px] py-[3px] float-left aspect-square">
    <div className="w-full h-full bg-newSep rounded-[6px] animate-pulse" />
  </div>
))}
```

### List loading (nuevo)

```tsx
{isLoading && [...new Array(8)].map((_, i) => (
  <div className="flex items-center gap-[12px] h-[52px] px-[8px]">
    <div className="w-[40px] h-[40px] bg-newSep rounded-[4px] animate-pulse" />
    <div className="flex-1 h-[12px] bg-newSep rounded animate-pulse" />
    <div className="w-[80px] h-[12px] bg-newSep rounded animate-pulse" />
  </div>
))}
```

---

## 9. Invariantes de no-regresión

| Invariante | Descripción |
|-----------|-------------|
| SWR key estable | `['get-media', page, search, activeFolder]` — no cambia con `viewMode` ni `zoomLevel` |
| `selectedForMove` cross-view | Un item seleccionado en grid sigue seleccionado al cambiar a list |
| Paginación intacta | `<Pagination>` aparece en ambas vistas si `data.pages > 1` |
| Modal standalone | En modo modal (insertar media en post), la vista default es siempre grid |
| Float layout | La clase `float-left` + `aspect-square` se mantiene en grid; list usa flex-col |
| `w8-max` eliminada de los tiles | Reemplazada por `style` inline — `global.scss` no se toca |
| Badge de carpeta en list | Columna "Carpeta" en list view sustituye el badge overlay del grid |
| Checkbox de selección | Funciona igual en grid (top-left overlay) y list (columna 0) |
| Acciones delete | Grid: `DeleteCircleIcon` en hover top-right. List: botón en hover al final de fila |

---

## 10. Checklist de implementación

### Feature A — Tab pendiente
- [ ] Insertar tab `pendingFolderName` en el strip (entre folders persistidas y `+ New folder`)
- [ ] Estilo dashed semi-transparente cuando inactivo
- [ ] Botón `✕` para descartar (`setPendingFolderName(null)`)
- [ ] Empty state contextual cuando `activeFolder === pendingFolderName && !data?.results?.length`
- [ ] Eliminar banner amarillo actual (redundante)

### Feature B — Toggle Grid/List
- [ ] Añadir estado `viewMode: 'grid' | 'list'`
- [ ] Añadir controles de toggle en barra superior
- [ ] Implementar `ListView` template con las 5 columnas descritas
- [ ] Skeleton de loading para list view
- [ ] Verificar que `selectedForMove` se mantiene al cambiar de vista

### Feature C — Zoom
- [ ] Añadir estado `zoomLevel: ZoomLevel` (default: 6)
- [ ] Añadir constante `ZOOM_LEVELS = [3, 4, 5, 6, 8, 10]`
- [ ] Sustituir `w8-max` en tiles por `style` inline calculado
- [ ] Sustituir `w8-max` en skeleton de loading
- [ ] Añadir slider + botones `−`/`+` en barra superior
- [ ] Ocultar controles de zoom en `viewMode === 'list'`

### Integración final
- [ ] Commit en `custom/postiz-dc`
- [ ] Build + deploy en Beelink
- [ ] Validación manual: crear carpeta → ver tab pendiente → mover item → zoom in/out → cambiar a list
- [ ] Cherry-pick a `feature/media-folders` para expandir upstream PR

---

## 11. Referencias de código

| Referencia | Línea aprox | Descripción |
|-----------|-------------|-------------|
| `w8-max` CSS | `global.scss:800` | Clase de ancho de tile (a sustituir con `style` inline) |
| Grid tile render | `media.component.tsx:787–874` | El `.map()` que genera los thumbnails |
| Skeleton loading | `media.component.tsx:764–776` | 16 placeholders animados |
| Tab strip | `media.component.tsx:539–560` | Render de las carpetas persistidas |
| `pendingFolderName` banner | `media.component.tsx:~639` | Banner amarillo a eliminar |
| `moveToFolder` | `media.component.tsx:~290` | PUT /media/move + mutateFolders |
| `loadFolders` SWR | `media.component.tsx:~244` | GET /media/folders |
| `loadMedia` SWR | `media.component.tsx:~230` | GET /media con folder param |
| `MediaController` | `media.controller.ts` | Orden de registro de rutas — crítico |
| `MediaRepository.getFolders` | `media.repository.ts` | `SELECT DISTINCT folder WHERE folder IS NOT NULL` |

---

*Documento creado: 2026-06-19. Autor: Antigravity (senior dev session).*
