# TECH-SPEC — Media Library UX: Hierarchical Folder Sidebar + List View + Zoom

> **Asociado a:** PR-002 (`feat(media): virtual folder organization + hierarchical sidebar + list/grid view + zoom`)
> **Rama:** `custom/postiz-dc` (producción) / `feature/media-folders` (upstream PR pendiente)
> **Commit actual:** `a9b58852`
> **Última actualización:** 2026-06-19

---

## 1. Contexto y motivación

### El problema original

La biblioteca de medios de Postiz presentaba dos carencias estructurales:

1. **Sin organización jerárquica sostenible:** los tabs planos (un tab por carpeta) no escalan — con 20-30 carpetas el strip colapsa a múltiples líneas.
2. **Sin modos de vista ni zoom:** el grid de 6 columnas fijas es la única opción.

### La solución

Cuatro mejoras cohesivas:

| Feature | Complejidad | Backend | Frontend |
|---------|-------------|---------|----------|
| A. Sidebar jerárquico colapsable | Media | ✅ SQL cascada en rename | ✅ parseFolderTree + árbol 2 niveles |
| B. Tab de carpeta pendiente visible | Mínima | ❌ sin cambios | ✅ solo JSX |
| C. Toggle Grid / List view | Baja | ❌ sin cambios | ✅ estado + template |
| D. Control de zoom (tamaño de tile) | Mínima | ❌ sin cambios | ✅ estado + CSS inline |

---

## 2. Mapa de archivos involucrados

```
apps/frontend/src/
└── components/media/
    └── media.component.tsx          ← ARCHIVO PRINCIPAL — toda la UI de MediaBox

libraries/nestjs-libraries/src/
├── database/prisma/
│   ├── schema.prisma                ← Media.folder String? + @@index([folder])
│   └── media/
│       ├── media.repository.ts      ← getFolders(), moveMedia(), renameFolder() (SQL cascada)
│       └── media.service.ts         ← proxies delgados
└── dtos/media/
    ├── move.media.dto.ts            ← { ids: string[], folder: string | null }
    └── rename.folder.dto.ts         ← { oldName: string, newName: string }

apps/backend/src/api/routes/
└── media.controller.ts              ← endpoints /media/folders, /media/move, /media/rename-folder
```

---

## 3. Modelo de datos — Path-based hierarchy

### Principio fundamental

No hay tabla `Folder`. Las carpetas son **valores del campo `folder: String?`** en `Media`.
La jerarquía se expresa como un path-string separado por `/`:

```
folder = null            → Root (sin carpeta asignada)
folder = "Nike"          → Carpeta raíz "Nike"
folder = "Nike/Diseños"  → Subcarpeta "Diseños" bajo "Nike"
folder = "Nike/Videos"   → Subcarpeta "Videos" bajo "Nike"
```

### Por qué este modelo es correcto

| Propiedad | Garantía |
|-----------|---------|
| **Cero schema extra** | Usa el campo `folder` ya existente, mismo tipo `String?` |
| **Rename cascada atómica** | Una query SQL con `REPLACE()+LIKE` actualiza todos los hijos |
| **Parseable en cliente** | `split('/')` + `reduce()` → árbol en < 10 líneas |
| **Backwards compatible** | `folder = null` = root; `GET /media` sin `?folder=` = todo el catálogo |
| **Sin orphans** | Si mueves todos los items de `Nike/Diseños`, el DISTINCT deja de devolver ese path |

---

## 4. Backend — `renameFolder` con SQL cascada

### El problema del rename jerárquico

Con el `updateMany` de Prisma (exact-match), renombrar `"Nike"` a `"Adidas"` no afectaría a `"Nike/Diseños"`. Quedaría `"Nike/Diseños"` huérfano.

### La solución

```typescript
// media.repository.ts
async renameFolder(org: string, dto: RenameFolderDto): Promise<void> {
  const { oldName, newName } = dto;
  const oldTrimmed = oldName.trim();
  const newTrimmed = newName.trim();

  // Guard: no-op si nombre no cambia
  if (oldTrimmed === newTrimmed) return;

  const prefix = `${oldTrimmed}/`;

  // Cast explícito: PrismaRepository<'media'>.model es Pick<PrismaService, 'media'>
  // en tipos, pero en runtime ES PrismaService (extends PrismaClient → tiene $queryRaw).
  const prisma = this._media.model as unknown as import('@prisma/client').PrismaClient;

  await prisma.$queryRaw<{ count: bigint }[]>(
    Prisma.sql`
      UPDATE "Media"
      SET folder = REPLACE(folder, ${oldTrimmed}, ${newTrimmed})
      WHERE "organizationId" = ${org}
        AND (
          folder = ${oldTrimmed}
          OR folder LIKE ${prefix + '%'}
        )
    `
  );
}
```

**Garantías:**
- **Inyección-safe:** usa `Prisma.sql` (tagged template) — parámetros escapados por Prisma.
- **Precision:** el `LIKE 'Nike/%'` evita renombrar `"NikeAlt"` cuando se renombra `"Nike"`.
- **Atómico:** una sola `UPDATE` — sin ventana de inconsistencia entre registros.

---

## 5. Frontend — `parseFolderTree`

### Implementación real — IIFE inline en el JSX

No es una función nombrada separada. Es una IIFE (`(() => { ... })()`) dentro del `return` del componente, que construye el árbol y retorna directamente el JSX del sidebar. Esto evita re-renders innecesarios y mantiene el scope de `expandedBrands`, `pendingFolderName`, etc. sin props drilling.

```typescript
// Dentro del JSX de MediaBox — IIFE que construye árbol y retorna JSX
{(() => {
  interface FolderNode { name: string; path: string; children: FolderNode[]; }
  const tree: FolderNode[] = [];
  const map: Record<string, FolderNode> = {};

  // Sort garantiza que padres aparecen antes que hijos en la iteración
  const sorted = [...(folders as string[])].sort();
  for (const path of sorted) {
    const segments = path.split('/');
    const name = segments[segments.length - 1];
    const node: FolderNode = { name, path, children: [] };
    map[path] = node;
    if (segments.length === 1) {
      tree.push(node);
    } else {
      // Solo 2 niveles en UI — sub-paths más profundos van bajo el brand (segments[0])
      const parentPath = segments[0];
      if (!map[parentPath]) {
        const parentNode: FolderNode = { name: parentPath, path: parentPath, children: [] };
        map[parentPath] = parentNode;
        tree.push(parentNode);
      }
      map[parentPath].children.push(node);
    }
  }

  // Merge pendingFolderName en el árbol (sin presencia en DB)
  if (pendingFolderName) {
    const segs = pendingFolderName.split('/');
    if (segs.length === 1 && !map[pendingFolderName]) {
      tree.push({ name: pendingFolderName, path: pendingFolderName, children: [] });
    } else if (segs.length > 1 && map[segs[0]]) {
      const alreadyIn = map[segs[0]].children.some(c => c.path === pendingFolderName);
      if (!alreadyIn) map[segs[0]].children.push({ name: segs[segs.length-1], path: pendingFolderName, children: [] });
    }
  }

  // ... renderNode() + return JSX
})()}
```

**Input:** `["Nike", "Nike/Diseños", "Nike/Videos", "Adidas"]`
**Output:**
```json
[
  { "name": "Nike", "path": "Nike", "children": [
    { "name": "Diseños", "path": "Nike/Diseños", "children": [] },
    { "name": "Videos",  "path": "Nike/Videos",  "children": [] }
  ]},
  { "name": "Adidas", "path": "Adidas", "children": [] }
]
```

---

## 6. Frontend — Sidebar UI

### Layout

```
╔═══════════════╗  ╔══════════════════════════════════════════╗
║ ☰ Folders     ║  ║ [Search................] [⊞][≡] [−●+] [+]║
║               ║  ║──────────────────────────────────────────║
║ ● All media   ║  ║ ☐ 🖼 banner.png  Nike/Diseños  img  ✕   ║
║ ○ No folder   ║  ║ ☐ 🎬 spot.mp4   Nike/Videos   vid  ✕   ║
║               ║  ║ ☐ 🖼 logo.svg   Adidas         img  ✕   ║
║ ▼ Nike        ║  ║                                          ║
║   ├ Diseños   ║  ║                                          ║
║   └ Videos    ║  ║                                          ║
║ ▶ Adidas      ║  ║                                          ║
║               ║  ║ [← Cancel]           [Add selected media]║
╚═══════════════╝  ╚══════════════════════════════════════════╝
```

### Comportamientos del sidebar

| Elemento | Acción | Resultado |
|----------|--------|--------|
| Nodo raíz (click) | `setActiveFolder("Nike")` + auto-expand | Filtra exact match `folder = 'Nike'` |
| Nodo raíz (chevron) | toggle `expandedBrands` | Expande/colapsa hijos sin cambiar `activeFolder` |
| Nodo hijo (click) | `setActiveFolder("Nike/Diseños")` | Filtra exact match `folder = 'Nike/Diseños'` |
| Hover nodo raíz | Muestra `+` (subfolder) + `✎` (rename) | Solo para nodos no-pending |
| `+` new subfolder | `setActiveFolder(brand)` + `setExpandedBrands` + `setCreatingFolder(true)` | Abre el input inline en el sidebar |
| `✎` rename | `renameFolderHandler(path)` | prompt → `PUT /media/rename-folder` con cascada SQL |
| Nodo dashed (click) | `setActiveFolder(pendingPath)` | Empty state contextual |
| Nodo dashed (`✕`) | `setPendingFolderName(null)` | Descarta la carpeta virtual |

> ⚠️ El `+` de subfolder NO llama directamente a `setPendingFolderName`. Abre el input inline del sidebar y navega al nodo brand. Es el `createFolder()` (al confirmar el input) el que construye el path y llama `setPendingFolderName("brand/sub")`.

### Estado

```typescript
const [sidebarOpen, setSidebarOpen]       = useState<boolean>(!standalone);
const [expandedBrands, setExpandedBrands] = useState<Set<string>>(new Set());
```

---

## 7. Flujo de datos completo

### 7.1 Carga

```
MediaBox mount
  ├─ loadMedia() → GET /media?page=N[&search=S][&folder=F]
  │    SWR key: `get-media-${page}-${debouncedSearch}-${activeFolder ?? 'all'}`
  │    Respuesta: { results: Media[], pages: number }
  │
  └─ loadFolders() → GET /media/folders
       SWR key: 'get-media-folders'
       Respuesta: string[]  — ["Nike", "Nike/Diseños", "Adidas"]
       → árbol construido por IIFE inline en el JSX del sidebar
```

> ℹ️ La SWR key de media es un **template string** (no un array tuple). Cualquier cambio en `page`, `debouncedSearch` o `activeFolder` invalida la caché automáticamente.

### 7.2 Creación de subcarpeta

```
Usuario en sidebar, hover "Nike" → click + (add subfolder)
  ├─ setActiveFolder("Nike")
  ├─ setExpandedBrands(prev => prev.add("Nike"))
  └─ setCreatingFolder(true)  ← abre el input inline en el sidebar

Usuario escribe "NombreNueva" → Enter
  └─ createFolder() se ejecuta:
       const parentPath = activeFolder.split('/')[0]  // = "Nike"
       const fullPath = "Nike/NombreNueva"
       setPendingFolderName("Nike/NombreNueva")
       setExpandedBrands(prev => prev.add("Nike"))
       → sidebar muestra nodo dashed bajo Nike

Usuario selecciona items → Move to → [Nike/NombreNueva]
  └─ PUT /media/move  { ids: [...], folder: "Nike/NombreNueva" }
     └─ onSuccess:
          ├─ mutateFolders() → GET /media/folders → árbol actualizado
          ├─ mutate()        → GET /media?folder=Nike/NombreNueva
          ├─ setSelectedForMove([])
          └─ setPendingFolderName(null)  ← ya persistida
```

### 7.3 Rename de marca (cascada)

```
Usuario hover "Nike" → click ✎ → prompt "Adidas"
  └─ PUT /media/rename-folder  { oldName: "Nike", newName: "Adidas" }
     └─ backend SQL:
          UPDATE Media SET folder = REPLACE(folder, 'Nike', 'Adidas')
          WHERE org = X AND (folder = 'Nike' OR folder LIKE 'Nike/%')
          → "Nike"         → "Adidas"
          → "Nike/Diseños" → "Adidas/Diseños"
          → "Nike/Videos"  → "Adidas/Videos"
     └─ onSuccess:
          ├─ activeFolder prefix update (si activo era "Nike/Diseños" → "Adidas/Diseños")
          ├─ mutateFolders()
          └─ mutate()
```

---

## 8. API contract

### `GET /media?folder=<value>`

| Valor | SQL generado | Comportamiento |
|-------|-------------|----------------|
| Omitido | Sin `WHERE folder` | Todo el catálogo |
| `__root__` | `WHERE folder IS NULL` | Solo root |
| `"Nike"` | `WHERE folder = 'Nike'` | Exact match (solo esa carpeta) |
| `"Nike/Diseños"` | `WHERE folder = 'Nike/Diseños'` | Exact match subcarpeta |

> ℹ️ El sidebar muestra `Nike` → filtra `folder = 'Nike'` (no incluye hijos). Para ver TODO bajo Nike, el usuario navega nodo a nodo o clicamos en el nodo raíz que podría en el futuro hacer `LIKE 'Nike%'` si se requiere. Actualmente el exact-match es deliberado y más predecible.

### `GET /media/folders` → `string[]`

### `PUT /media/move` → `{ ids: string[], folder: string | null }`

### `PUT /media/rename-folder` → `{ oldName: string, newName: string }`

> ⚠️ El orden de registro en `media.controller.ts` es crítico:
> `GET /media/folders` y `PUT /media/move` deben registrarse **antes** de `GET /media/:id`.

---

## 9. Invariantes de no-regresión

| Invariante | Descripción |
|-----------|-------------|
| SWR key estable | `['get-media', page, search, activeFolder]` — no cambia con `viewMode` ni `zoomLevel` |
| `selectedForMove` cross-view | Items seleccionados en grid siguen seleccionados al pasar a list |
| Paginación intacta | `<Pagination>` aparece en ambas vistas si `data.pages > 1` |
| Modal standalone | En modo modal, sidebar oculto por defecto (`sidebarOpen = false`) |
| Rename precision | `LIKE 'Nike/%'` evita que `"NikeAlt"` sea modificado al renombrar `"Nike"` |
| `$queryRaw` type-safe | Cast documentado con comentario; `Prisma.sql` previene inyección |
| Badge en grid | `media.folder` en thumbnail top-right (truncado 80px) |
| Columna en list | `media.folder ?? '—'` en columna 3 de list view |
| Checkbox de selección | Funciona igual en grid (overlay) y list (columna 0) |
| `w8-max` eliminada | Sustituida por `style` inline — `global.scss` no se toca |

---

## 10. Zoom — tabla de niveles

| Index | Cols | Tile aprox (1200px) | Caso de uso |
|-------|------|---------------------|-------------|
| 0 | 3 | 400px | Ver detalles grandes |
| 1 | 4 | 300px | Thumbnails cómodos |
| 2 | 5 | 240px | Balance |
| 3 | 6 | 200px | **Default (useState inicial)** |
| 4 | 8 | 150px | Muchos archivos |
| 5 | 10 | 120px | Densidad máxima |

Implementación: `style={{ width: \`calc(100% / ${zoomLevel})\`, maxWidth: \`calc(100% / ${zoomLevel})\` }}` en tile y en cada skeleton. Los controles (slider + `−`/`+`) se ocultan con `{viewMode === 'grid' && <ZoomControls />}`.

---

## 11. Skeleton / loading states

### Grid loading

```tsx
{isLoading && viewMode === 'grid' && [...new Array(16)].map((_, i) => (
  <div style={{ width: `calc(100% / ${zoomLevel})` }}
       className="px-[3px] py-[3px] float-left aspect-square" key={i}>
    <div className="w-full h-full bg-newSep rounded-[6px] animate-pulse" />
  </div>
))}
```

### List loading

```tsx
{isLoading && viewMode === 'list' && [...new Array(8)].map((_, i) => (
  <div key={i} className="flex items-center gap-[12px] h-[52px] px-[8px]">
    <div className="w-[40px] h-[40px] bg-newSep rounded-[4px] animate-pulse flex-shrink-0" />
    <div className="flex-1 h-[12px] bg-newSep rounded animate-pulse" />
    <div className="w-[80px] h-[12px] bg-newSep rounded animate-pulse" />
  </div>
))}
```

---

## 12. Referencias de código (post-refactor)

| Referencia | Línea real | Descripción |
|-----------|------------|-------------|
| IIFE árbol (parseFolderTree inline) | ~549–787 | IIFE que construye `FolderNode[]` y retorna JSX del sidebar |
| Estado `sidebarOpen` + `expandedBrands` | ~229–232 | `useState(!standalone)` + `useState(new Set())` |
| `createFolder()` | ~267–292 | `activeFolder.split('/')[0]` = parent brand; construye fullPath |
| `renameFolderHandler()` | ~322–355 | `split('/').pop()` para label; reconstruye path completo nuevo |
| SWR key media | ~250 | Template string: `` `get-media-${page}-${search}-${folder ?? 'all'}` `` |
| Move-to dropdown | ~790–900 | Usa misma lógica de árbol con indent por depth |
| `renameFolder()` backend | `media.repository.ts` L130–163 | SQL REPLACE()+LIKE cascada, $queryRaw con cast PrismaClient |
| `ZOOM_LEVELS` | ~226 | `[3, 4, 5, 6, 8, 10] as const` — declarado dentro del componente |
| Iconos de nodo | ~644–645 | Brand raíz: `🗂`, sub-carpeta: `📁`, pendiente: `✨` |

---

*Documento actualizado: 2026-06-19. Arquitectura migrada de tabs planos a sidebar jerárquico path-based. Commit: `a9b58852`.*
