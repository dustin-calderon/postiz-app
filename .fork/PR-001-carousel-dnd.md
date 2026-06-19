# PR-001 — `fix(carousel): sync local state on drag-drop reorder`

> **Rama:** `feature/carousel-dnd` (a crear desde `upstream/main`)
> **Estado:** 🟡 EN VALIDACIÓN — pendiente test manual en producción
> **Fecha inicio:** 2026-06-19 | **Fork:** `dustin-calderon/postiz-app`

---

## 1. Contexto

Postiz ya incluía `react-sortablejs` en `media.component.tsx` para reordenar medios en carruseles. Sin embargo, el `setList` de `ReactSortable` **solo llamaba al `onChange` del padre** sin actualizar el estado local `currentMedia`. Esto causaba que el orden visual revertiera al estado anterior en el siguiente render, haciendo la funcionalidad inútil.

Este PR corrige ese bug y añade los fixes de calidad directamente relacionados descubiertos durante la auditoría.

---

## 2. Problema exacto (upstream pre-fix)

```tsx
// ❌ upstream: setList no sincroniza el estado local
<ReactSortable
  list={currentMedia}
  setList={(value) =>
    onChange({ target: { name: 'upload', value } })
  }
>
```

Al soltar un elemento tras el drag:
1. `ReactSortable` llama `setList(nuevoOrden)`
2. El `onChange` notifica al padre con el nuevo orden ✅
3. Pero `currentMedia` (estado local del componente) **no se actualiza**
4. React re-renderiza → `currentMedia` sigue con el orden anterior → la UI revierte ❌

---

## 3. Fix implementado

**Archivo:** `apps/frontend/src/components/media/media.component.tsx`

### Commit `6cef56a2` — fix principal

```tsx
// ✅ fix: setList sincroniza currentMedia local + notifica al padre
<ReactSortable
  list={currentMedia}
  setList={(value) => {
    setCurrentMedia(value);                              // ← añadido
    onChange({ target: { name: 'upload', value } });
  }}
>
```

### Commit `171ca8bc` — fixes de calidad relacionados (misma auditoría)

```tsx
// ✅ fix: useState declarado ANTES del useEffect que lo usa
const [currentMedia, setCurrentMedia] = useState(value);  // movido arriba
useEffect(() => {
  if (value) setCurrentMedia(value);
}, [value]);

// ✅ fix: addNewMedia dep array completo (stale closure)
const addNewMedia = useCallback(
  (m) => { ... },
  [currentMedia, onChange]  // onChange añadido — antes: [currentMedia]
);

// ✅ fix: clearMedia dep array completo (stale closure, fix anterior)
const clearMedia = useCallback(
  () => { ... },
  [currentMedia, onChange]  // onChange añadido — antes: [currentMedia]
);
```

### Commit `40bd9ab0` — limpieza de debug (mismo bloque de trabajo)

```diff
// new.uploader.tsx — eliminado console.log residual de producción
uppy2.on('complete', async (result) => {
-  console.log(result);
  for (const file of [...result.successful]) {
```

---

## 4. Archivos modificados (diff contra `upstream/main`)

| Archivo | Cambios | Tipo |
|---------|---------|------|
| `apps/frontend/src/components/media/media.component.tsx` | 14 líneas (+7/-8) | Feature + bug fixes |
| `apps/frontend/src/components/media/new.uploader.tsx` | 1 línea (-1) | Limpieza |

> `posts.service.ts` — ya no aparece en el diff final (línea en blanco eliminada).

---

## 5. Qué NO va en este PR

| Cambio | Razón |
|--------|-------|
| `build.sh` (prune tag-based) | Infraestructura del homelab, específica de nuestra instancia |
| `docker-compose.yml` | Configuración de producción privada |
| `postiz.env` | Secretos y config privada |
| Webhooks custom (implementados y revertidos) | Postiz ya tiene `WebhooksService` nativo. Sin valor upstream |

---

## 6. Checklist pre-PR

- [x] Código limpio (sin `console.log`, sin comentarios de debug)
- [x] Stale closures corregidas (3 dep arrays)
- [x] Hook order canónico (useState antes de useEffect)
- [x] 0 cambios de infraestructura en el diff
- [ ] **Test manual en producción** — crear carousel, reordenar, guardar, verificar que el orden persiste
- [ ] **Test publicación** — verificar que el carousel llega a Instagram en el orden correcto
- [ ] Confirmar que `pnpm tsc --noEmit` pasa sin errores nuevos (opcional antes de PR)
- [ ] Crear rama `feature/carousel-dnd` desde `upstream/main`
- [ ] Cherry-pick commits carousel hacia la rama limpia
- [ ] Abrir PR en `gitroomhq/postiz-app`

---

## 7. Cómo preparar la rama del PR (cuando esté validado)

```bash
ssh dchomeserver

# 1. Asegurarse de que upstream está al día
git -C /opt/repos/postiz-fork fetch upstream

# 2. Crear rama limpia desde upstream/main
git -C /opt/repos/postiz-fork checkout -b feature/carousel-dnd upstream/main

# 3. Cherry-pick solo los commits de carousel (en orden cronológico)
git -C /opt/repos/postiz-fork cherry-pick 6cef56a2  # fix: setList
git -C /opt/repos/postiz-fork cherry-pick 171ca8bc  # hook order + deps
git -C /opt/repos/postiz-fork cherry-pick 40bd9ab0  # console.log

# 4. Verificar el diff final (debe ser solo 2 archivos)
git -C /opt/repos/postiz-fork diff upstream/main --stat

# 5. Push y abrir PR desde GitHub
git -C /opt/repos/postiz-fork push origin feature/carousel-dnd
```

---

## 8. Título y descripción del PR (borrador)

**Título:**
```
fix(media): sync local carousel state on drag-drop reorder
```

**Descripción:**
```markdown
## Problem

`MultiMediaComponent` uses `ReactSortable` to reorder carousel media.
The `setList` callback only called `onChange` (to notify the parent form)
but did NOT update the local `currentMedia` state. This caused the UI to
visually revert to the previous order on the next render, making the
drag-and-drop feature non-functional.

## Fix

- `setList` now calls `setCurrentMedia(value)` before `onChange`, keeping
  the local state in sync with the sorted result.

## Related cleanup (same component, same audit)

- Moved `useState(value)` above the `useEffect` that references `setCurrentMedia`
  (canonical React hook declaration order)
- Added `onChange` to the dependency arrays of `addNewMedia` and `clearMedia`
  `useCallback` hooks (were stale closures — `onChange` was captured from the
  first render and never updated)
- Removed a stray `console.log(result)` from `new.uploader.tsx`

## Testing

- [ ] Create a post with multiple images
- [ ] Drag to reorder → UI should maintain the new order
- [ ] Save/schedule the post → order should persist
- [ ] Publish → carousel should arrive on Instagram in the new order
```

---

## 9. Historia de commits en `custom/postiz-dc`

```
58270cc5  chore: remove orphan blank line in posts.service.ts
171ca8bc  fix(media): correct hook order and complete useCallback dependency arrays
40bd9ab0  revert(webhooks): remove custom webhook — use Postiz native WebhooksService instead
7967c8d7  fix(audit): remediate 10 bugs found in post-implementation review
cf78a1ab  feat(webhooks): emit post.published event to outbound URLs
6cef56a2  fix(carousel): sync local state on drag-drop reorder       ← carousel origin
```

> Los commits `6cef56a2`, `40bd9ab0` y `171ca8bc` son los que van al PR (cherry-pick).
> El resto son infraestructura/experimentos que se quedan en `custom/postiz-dc`.

---

*Documento creado: 2026-06-19. Actualizar cuando el test manual esté completo.*
