# PR-002 — `feat(media): virtual folder organization for media library`

> **Rama:** `feature/media-folders` → upstream `main`
> **Estado:** ✅ PR #1 ABIERTO — https://github.com/dustin-calderon/postiz-app/pull/1
> **Fecha inicio:** 2026-06-19 | **Fork:** `dustin-calderon/postiz-app`
> **Commit upstream branch:** `eb458a50`
> **Commit en `custom/postiz-dc`:** `cae1892c` (cherry-pick)

---

## 1. Contexto

La biblioteca de medios de Postiz no ofrecía ningún mecanismo de organización.
Todos los assets (imágenes, vídeos) vivían en una lista plana paginada, sin
posibilidad de filtrar por tipo de proyecto, campaña o cliente.

Este PR implementa un sistema de **carpetas virtuales** — un campo `folder` (string nullable)
en el modelo `Media`. No se crea ninguna tabla nueva ni relación adicional: las carpetas
son labels inferidos por consultas `DISTINCT`, lo que mantiene el footprint de schema
absolutamente mínimo.

---

## 2. Decisiones de diseño

| Decisión | Alternativa considerada | Razón elegida |
|----------|-------------------------|---------------|
| Label string en `Media.folder` | Tabla `Folder` con FK | Cero overhead, sin orphan management |
| Carpetas inferidas via `DISTINCT` | Tabla de gestión separada | Sin estado extra a mantener en sync |
| Sentinel `__root__` en query param | `null` en querystring | URL-safe, sin ambigüedad |
| Rename = `updateMany` en todos los items | Entidad con ID | Consistente con el modelo de borrado (reset a NULL) |
| `NULL` por defecto (root) | String vacío | Semánticamente correcto, compatible con índice |

**Estructura plana (no jerárquica):** Deliberadamente sin anidamiento padre-hijo.
La complejidad de jerarquías (breadcrumbs, mover subcarpetas) no aporta valor suficiente
para el caso de uso (biblioteca de assets de RRSS).

---

## 3. Archivos modificados

| Archivo | Tipo de cambio | Descripción |
|---------|---------------|-------------|
| `libraries/nestjs-libraries/src/database/prisma/schema.prisma` | Schema | `folder String?` + `@@index([folder])` en `Media` |
| `libraries/nestjs-libraries/src/dtos/media/move.media.dto.ts` | Nuevo | `{ ids: string[], folder: string \| null }` |
| `libraries/nestjs-libraries/src/dtos/media/rename.folder.dto.ts` | Nuevo | `{ oldName: string, newName: string }` |
| `libraries/nestjs-libraries/src/database/prisma/media/media.repository.ts` | Extendido | `getFolders()`, `moveMedia()`, `renameFolder()`, `getMedia()` con folder filter |
| `libraries/nestjs-libraries/src/database/prisma/media/media.service.ts` | Extendido | Proxies para los 3 nuevos métodos de repositorio |
| `apps/backend/src/api/routes/media.controller.ts` | Extendido | 3 endpoints nuevos + `?folder=` en `GET /media` |
| `apps/frontend/src/components/media/media.component.tsx` | Extendido | Folder UI completa en `MediaBox` |

---

## 4. API contract

### `GET /media?folder=<value>`

| Valor de `?folder=` | Comportamiento |
|---------------------|----------------|
| Omitido | Todo el catálogo (backwards compatible) |
| `__root__` | Solo items sin carpeta asignada |
| `<nombre>` | Solo items en esa carpeta |

### `GET /media/folders`

```json
["Campaigns", "Clients", "Q2-2026"]
```

### `PUT /media/move`

```json
{ "ids": ["id1", "id2"], "folder": "Campaigns" }
// folder: null → mueve a root
```

### `PUT /media/rename-folder`

```json
{ "oldName": "Campaigns", "newName": "Campaigns-2026" }
```

---

## 5. Cambios en frontend (MediaBox)

```
┌─────────────────────────────────────────────────────────────┐
│ [All] [No folder] [📁 Campaigns] [📁 Clients] [+ New folder]│
│                                               [2 selected ▼] │
├─────────────────────────────────────────────────────────────┤
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                        │
│ │ ☐img │ │ ☐img │ │ ☐img │ │ ☐img │  ← checkbox en hover  │
│ │Cli.. │ │      │ │      │ │      │  ← badge carpeta        │
│ └──────┘ └──────┘ └──────┘ └──────┘                        │
└─────────────────────────────────────────────────────────────┘
```

**Interacciones implementadas:**

- **Tab strip** — filtra el grid instantáneamente (SWR key incluye `activeFolder`)
- **New folder** — input inline con `Enter` para confirmar, `Escape` para cancelar
- **Rename folder** — pencil icon en hover de la tab → `window.prompt` → `PUT /media/rename-folder`
- **Checkbox de selección** — aparece en `group-hover`, esquina superior izquierda, NO interfiere con el mecanismo de "select for insert" (borde morado)
- **Bulk move bar** — aparece cuando ≥1 checkbox activo → dropdown con carpetas destino
- **Badge de carpeta** — etiqueta en esquina superior derecha de cada thumbnail

---

## 6. Backwards compatibility

- Todo el media existente tiene `folder = NULL` (root) → **sin migración de datos**
- `GET /media` sin `?folder=` devuelve todo el catálogo → **comportamiento anterior intacto**
- El cliente Prisma se regenera automáticamente con `pnpm run prisma-generate`
- La columna se aplica en producción con `pnpm run prisma-db-push` (proyecto usa `db push`, no migrations)

---

## 7. Checklist pre-PR

- [x] Schema actualizado con `folder String?` + index
- [x] DTOs con validación `class-validator`
- [x] Repository: tipos explícitos (`Prisma.MediaWhereInput`) — sin errores TS
- [x] Controller: 3 nuevos endpoints + `?folder=` en GET
- [x] Frontend: tab strip, creación, rename, checkbox, bulk move, badge
- [x] Prisma Client regenerado (`pnpm run prisma-generate`)
- [x] Zero errores TS en archivos de media (errores pre-existentes del upstream ignorados)
- [x] Commit atómico en `feature/media-folders` (upstream-clean)
- [x] Cherry-pick aplicado a `custom/postiz-dc` (el `.fork/` vive en producción)
- [ ] Validación manual en producción (pendiente `prisma-db-push` en Beelink)
- [ ] Confirmación de aceptación upstream

---

## 8. Historia de commits

```
custom/postiz-dc:
  cae1892c  feat(media): add virtual folder organization  ← cherry-pick de PR

feature/media-folders (rama limpia upstream):
  eb458a50  feat(media): add virtual folder organization  ← commit del PR
```

---

## 9. Deployment en Beelink (post-merge)

```bash
# Windows — actualizar custom/postiz-dc post upstream merge:
git fetch upstream
git rebase upstream/main custom/postiz-dc  # eb458a50 desaparecerá (ya está mergeado)
git push origin custom/postiz-dc

# Beelink homeserver:
ssh dchomeserver
git -C /opt/repos/postiz-fork pull origin custom/postiz-dc
pnpm run prisma-db-push   # ← aplica ALTER TABLE Media ADD COLUMN folder TEXT
./build.sh
```

---

*Documento creado: 2026-06-19. PR abierto: 2026-06-19.*
