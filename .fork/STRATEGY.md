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
                     git rebase (Windows)
                               │
custom/postiz-dc               ●── [feat temporal → luego PR o se queda]
                               ●── [infra: build.sh]         ← permanente
                               ●── [infra: docker-compose]   ← permanente
                               │
                         git push origin
                               │
                        origin/custom/postiz-dc  (GitHub)
                               │
                    git pull (Beelink homeserver)
                               │
                         ./build.sh → Docker producción
```

**Reglas:**
- Todo el trabajo Git ocurre en **Windows** (este repo).
- El homeserver **solo** hace `git pull` + `./build.sh`. Nunca operaciones Git propias.
- Docker siempre se construye desde `custom/postiz-dc`. Nunca desde `upstream/main`.

---

## Commits privados permanentes (solo infra)

| Commit | Descripción | Va a upstream |
|--------|-------------|---------------|
| `chore: add build.sh` | Prune de imágenes Docker por tag, específico del homelab | ❌ Nunca |
| `chore: docker-compose + postiz.env` | Configuración de producción privada, secretos | ❌ Nunca |

> Verificar con: `git diff upstream/main custom/postiz-dc --stat -- ':!postiz.env' ':!docker-compose.yml' ':!build.sh'`
> Output esperado: **0 archivos** cuando la rama está limpia (sin features en vuelo).
> Si aparecen archivos, son features temporales (legítimos) o ruido a limpiar.

---

## PRs activos / contribuciones upstream

| ID | Rama | Estado | Doc | PR upstream |
|----|------|--------|-----|-------------|
| PR-001 | `feature/carousel-dnd` | ✅ Abierto | [`PR-001-carousel-dnd.md`](./PR-001-carousel-dnd.md) | [#1613](https://github.com/gitroomhq/postiz-app/pull/1613) |

---

## Ciclo de vida — los tres escenarios

La estructura es siempre la misma: todo el trabajo Git en **Windows**, luego
un `git pull + ./build.sh` en el homeserver para desplegar.

---

### 1. Sincronizar upstream y redesplegar

Cuándo: hay una nueva versión de Postiz y quieres sus mejoras.

**Windows:**
```bash
git fetch upstream
git rebase upstream/main custom/postiz-dc
# Si tu PR ya fue mergeado: Git detecta el duplicate y lo salta solo.
# Si hay conflicto: es código que tú escribiste → resolución trivial.
git push origin custom/postiz-dc
```

**Homeserver:**
```bash
ssh dchomeserver
git -C /opt/repos/postiz-fork pull origin custom/postiz-dc
./build.sh
```

Resultado: tienes lo último de upstream + todos tus features. Sin regresión.

---

### 2. Añadir un nuevo feature y desplegarlo

Cuándo: quieres una mejora nueva (con o sin intención de PR).

**Windows:**
```bash
git checkout custom/postiz-dc
# ... desarrollas el feature ...
git commit -m "feat(xxx): descripción"
git push origin custom/postiz-dc
```

**Homeserver:**
```bash
ssh dchomeserver
git -C /opt/repos/postiz-fork pull origin custom/postiz-dc
./build.sh
```

Si luego decides subirlo como PR upstream (en Windows):
```bash
git checkout -b feature/xxx upstream/main
git cherry-pick --no-commit <tus-shas>
# filtrar archivos privados → commit limpio → PR
```

---

### 3. Verificar si un PR fue mergeado y sincronizar

Cuándo: han pasado semanas, quieres saber si aceptaron tu contribución.

**Windows:**
```bash
git fetch upstream
git log upstream/main --oneline | head -30  # ¿aparece tu fix?
git rebase upstream/main custom/postiz-dc   # tu commit desaparece solo
git push origin custom/postiz-dc
```

**Homeserver:**
```bash
ssh dchomeserver
git -C /opt/repos/postiz-fork pull origin custom/postiz-dc
./build.sh
```

---

**Frecuencia recomendada:** rebasar antes de empezar cualquier feature nuevo,
o al menos una vez al mes. A más tiempo sin rebasar, más probable que upstream
haya tocado los mismos archivos → conflictos más largos.

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

## Qué NO va a upstream (se queda en el fork)

| Archivo | Razón |
|---------|-------|
| `postiz.env` | Secretos de producción |
| `docker-compose.yml` | Configuración privada de la instancia |
| `build.sh` | Script de homelab, específico de esta instalación |

---

## Estado actual del fork

```
Rama producción:  custom/postiz-dc  (siempre)
Docker build:     ./build.sh desde custom/postiz-dc
upstream fetch:   ✅ configurado (git fetch upstream)

Delta vs upstream (excl. infra privada):
  → 2 archivos (carousel fix) — en feature/carousel-dnd

PRs:
  PR-001 carousel-dnd:  ✅ ABIERTO — https://github.com/gitroomhq/postiz-app/pull/1613
```

Última actualización: 2026-06-19 — PR #1613 abierto en upstream.
