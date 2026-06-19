# Fork Strategy — `dustin-calderon/postiz-app`

> **Upstream:** `https://github.com/gitroomhq/postiz-app`
> **Fork:** `https://github.com/dustin-calderon/postiz-app`
> **Instancia producción:** Beelink homeserver (`/opt/repos/postiz-fork`)
> **Última revisión:** 2026-06-19

---

## Modelo mental

Este fork usa un **patch stack**: una pila mínima de commits privados que vive
**siempre encima de `upstream/main`**. Upstream es la base, no el punto de
partida histórico.

```
upstream/main  ──●──●──●──●──●──▶  (evoluciona continuamente)
                              │
                    rebase semanal
                              │
custom/postiz-dc              ●── [infra: build.sh]
                              ●── [infra: docker-compose + postiz.env]
```

**Regla de oro:** `custom/postiz-dc` contiene únicamente configuración de la
instancia privada. Ningún bugfix de producto vive aquí — esos van a upstream.

---

## Commits privados permanentes (solo infra)

| Commit | Descripción | Va a upstream |
|--------|-------------|---------------|
| `chore: add build.sh` | Prune de imágenes Docker por tag, específico del homelab | ❌ Nunca |
| `chore: docker-compose + postiz.env` | Configuración de producción privada, secretos | ❌ Nunca |

> Verificar con: `git diff upstream/main custom/postiz-dc --stat -- ':!postiz.env' ':!docker-compose.yml' ':!build.sh'`
> Output esperado: **0 archivos**. Si hay más, hay ruido que limpiar.

---

## PRs activos / contribuciones upstream

| ID | Rama | Estado | Commits |
|----|------|--------|---------|
| PR-001 | `feature/carousel-dnd` | 🟡 En preparación | `6cef56a2`, `171ca8bc`, `40bd9ab0` → squash limpio |

### PR-001 — carousel drag-and-drop

**Fix:** `ReactSortable.setList` no sincronizaba el estado local `currentMedia`,
causando que el orden visual revertiera en el siguiente render.

**Archivos afectados (solo estos dos):**
- `apps/frontend/src/components/media/media.component.tsx`
- `apps/frontend/src/components/media/new.uploader.tsx`

**Estado del test manual:** ⬜ pendiente en producción.

Ver `PR-001-carousel-dnd.md` para contexto completo y borrador de descripción.

---

## Workflow de sincronización con upstream

```bash
ssh dchomeserver
git -C /opt/repos/postiz-fork fetch upstream

# Rebasar commits privados encima del nuevo upstream
git -C /opt/repos/postiz-fork rebase upstream/main custom/postiz-dc
```

**Frecuencia recomendada:** semanal, o antes de preparar cualquier PR.

**Si hay conflicto post-merge de un PR propio:**
Git usa patch-id para detectar duplicados. Si el maintainer no modificó el
código, Git omite el commit automáticamente. Si lo modificó, el conflicto es
en las mismas líneas que tú escribiste — resolución trivial.

---

## Workflow de preparación de PR limpio

El PR **siempre** nace de `upstream/main`, nunca de `custom/postiz-dc`.

```bash
git fetch upstream
git checkout -b feature/<nombre> upstream/main

# Cherry-pick sin commitear para poder filtrar archivos privados
git cherry-pick --no-commit <sha1> <sha2> ...

# Descartar cualquier archivo que no pertenezca al PR
git restore --staged <archivo-no-relacionado>
git restore <archivo-no-relacionado>

# Verificar: solo deben aparecer los archivos del fix
git diff --cached --stat

# Commit único y atómico
git commit -m "fix(...): descripción"

# Push y abrir PR en GitHub
git push origin feature/<nombre>
```

**Por qué `--no-commit` y no cherry-pick directo:**
Los commits en `custom/postiz-dc` pueden mezclar cambios de producto con
residuos de experimentos (e.g., `posts.service.ts` en PR-001). El paso de
`restore` garantiza un diff 100% limpio antes de subir el PR.

---

## Qué NO va al fork

| Archivo | Razón |
|---------|-------|
| `postiz.env` | Secretos de producción |
| `docker-compose.yml` | Configuración privada de la instancia |
| `build.sh` | Script de homelab, sin valor upstream |
| Webhooks custom (revertidos) | Postiz ya tiene `WebhooksService` nativo completo |

---

## Estado actual del fork

```
Rama activa:     custom/postiz-dc
Delta vs upstream (excl. infra privada): 2 archivos (carousel fix)
upstream/main fetch: ✅ configurado
feature/carousel-dnd: ⬜ pendiente crear y abrir PR
```
