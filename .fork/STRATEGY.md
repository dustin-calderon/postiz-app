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
upstream/main  ──●──●──[PR merged]──●──●──▶
                               │
                     git rebase (cuando quieras)
                               │
custom/postiz-dc               ●── [feat temporal → luego PR o se queda]
                               ●── [infra: build.sh]         ← permanente
                               ●── [infra: docker-compose]   ← permanente
                               │
                         ./build.sh
                               │
                          Docker producción
```

**Regla de oro:** Docker **siempre** se construye desde `custom/postiz-dc`.
Nunca desde `upstream/main`. Los features viven aquí hasta que van a upstream
(y desaparecen solos en el rebase) o se quedan como privados.

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

## Ciclo de vida — los tres escenarios

### 1. Sincronizar upstream y redesplegar (sin perder features)

Cuándo: hay una nueva versión de Postiz y quieres sus mejoras.

```bash
ssh dchomeserver
git -C /opt/repos/postiz-fork fetch upstream
git -C /opt/repos/postiz-fork rebase upstream/main custom/postiz-dc
# Si un PR tuyo ya fue mergeado: Git detecta el duplicate y lo salta solo.
# Si hay conflicto: es en código que tú escribiste → resolución trivial.
./build.sh  # rebuild Docker desde custom/postiz-dc
```

Resultado: tienes lo último de upstream + todos tus features. Sin regresión.

---

### 2. Añadir un nuevo feature y desplegarlo

Cuándo: quieres una mejora nueva en tu instancia (con o sin intención de PR).

```bash
ssh dchomeserver
git -C /opt/repos/postiz-fork checkout custom/postiz-dc
# ... desarrollas el feature ...
git -C /opt/repos/postiz-fork commit -m "feat(xxx): descripción"
./build.sh  # desplegado con el feature nuevo
```

Si luego decides subirlo como PR upstream:
```bash
git checkout -b feature/xxx upstream/main
git cherry-pick --no-commit <tus-shas>
# filtrar archivos privados → commit limpio → PR
```

---

### 3. Confirmar si un PR fue mergeado y sincronizar

Cuándo: han pasado semanas, quieres saber si aceptaron tu contribución.

```bash
git -C /opt/repos/postiz-fork fetch upstream
# ¿Aparece tu fix en el log de upstream?
git log upstream/main --oneline | head -30

# Si está: rebasea — el commit tuyo desaparece de la pila automáticamente
git -C /opt/repos/postiz-fork rebase upstream/main custom/postiz-dc
./build.sh
```

El commit ya no es tuyo — es de upstream. Tu rama queda con solo los commits
realmente privados encima. Exactamente como debe ser.

---

**Frecuencia recomendada:** rebasar antes de empezar cualquier feature nuevo
o al menos una vez al mes. A más tiempo sin rebasar, más probable que upstream
haya tocado los mismos archivos que tú → conflictos más largos.

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
Rama producción:  custom/postiz-dc  (siempre)
Docker build:     ./build.sh desde custom/postiz-dc
upstream fetch:   ✅ configurado (git fetch upstream)

Delta vs upstream (excl. infra privada):
  → 2 archivos (carousel fix) — pendiente de limpiar en PR

PRs:
  PR-001 carousel-dnd:  🟡 en preparación — test manual pendiente
```
