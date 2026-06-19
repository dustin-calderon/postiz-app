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

### Función de parseo (nativa, sin deps)

```typescript
interface FolderNode {
  name: string;    // segmento display (último path component)
  path: string;    // path completo para setActiveFolder()
  children: FolderNode[];
}

function parseFolderTree(folders: string[]): FolderNode[] {
  const roots = new Map<string, FolderNode>();

  for (const f of folders) {
    const parts = f.split('/');
    const rootName = parts[0];

    if (!roots.has(rootName)) {
      roots.set(rootName, { name: rootName, path: rootName, children: [] });
    }

    if (parts.length === 2) {
      roots.get(rootName)!.children.push({
        name: parts[1],
        path: f,
        children: [],
      });
    }
    // Nivel > 2 ignorado deliberadamente (2 niveles cubre el caso de uso)
  }

  return Array.from(roots.values());
}
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
|----------|--------|-----------|
| Nodo raíz (click) | `setActiveFolder("Nike")` | Filtra todos los items bajo "Nike" y sus sub |
| Nodo raíz (chevron) | toggle `expandedBrands` | Expande/colapsa los hijos sin cambiar `activeFolder` |
| Nodo hijo (click) | `setActiveFolder("Nike/Diseños")` | Filtra solo esa subcarpeta |
| Hover nodo raíz | Muestra `✎` (rename) + `⊕` (subfolder) | — |
| `⊕` new subfolder | `setPendingFolderName("Nike/NuevaSub")` | Nodo dashed en el árbol bajo Nike |
| `✎` rename | `renameFolderHandler("Nike")` | prompt → `PUT /media/rename-folder` |
| Nodo dashed (click) | `setActiveFolder("Nike/NuevaSub")` | Empty state contextual |

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
  │    SWR key: ['get-media', page, search, activeFolder]
  │    Respuesta: { results: Media[], pages: number }
  │
  └─ loadFolders() → GET /media/folders
       SWR key: 'get-media-folders'
       Respuesta: string[]  — ["Nike", "Nike/Diseños", "Adidas"]
       → parseFolderTree() → árbol para sidebar
```

### 7.2 Creación de subcarpeta

```
Usuario en sidebar, hover "Nike" → click ⊕
  └─ setPendingFolderName("Nike/NombreNueva")
     → sidebar muestra nodo dashed bajo Nike
     → setActiveFolder("Nike/NombreNueva")
     → empty state contextual

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
| 3 | 6 | 200px | **Default** |
| 4 | 8 | 150px | Muchos archivos |
| 5 | 10 | 120px | Densidad máxima |

Implementación: `style={{ width: \`calc(100% / ${zoomLevel})\` }}` en tile y skeleton. Los controles (slider + `−`/`+`) se ocultan en `viewMode === 'list'`.

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

| Referencia | Descripción |
|-----------|-------------|
| `parseFolderTree()` | Líneas ~265–290 en `media.component.tsx` — string[] → FolderNode[] |
| Sidebar JSX | Líneas ~538–790 en `media.component.tsx` — árbol colapsable |
| `createFolder()` | Path-aware: detecta `activeFolder` para construir sub-path |
| `renameFolderHandler()` | Actualiza solo el último segmento del path; refresca `activeFolder` |
| Move-to dropdown | Árbol indentado con depth visual (misma `parseFolderTree`) |
| `renameFolder()` backend | `media.repository.ts` L~120–175 — SQL REPLACE()+LIKE cascada |
| `MediaController` | `media.controller.ts` — orden de rutas crítico (folders antes de /:id) |
| `ZOOM_LEVELS` | Constante en `media.component.tsx` — `[3, 4, 5, 6, 8, 10]` |

---

*Documento actualizado: 2026-06-19. Arquitectura migrada de tabs planos a sidebar jerárquico path-based. Commit: `a9b58852`.*
