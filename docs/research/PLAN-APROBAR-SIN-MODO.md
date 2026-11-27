# Plan — aprobar con `Status`, sin la propiedad `modo`

> Transitorio: se borra al fusionar. Lo que queda vivo va a [[CONTENT_PIPELINE_NOTION_SCHEMA|NOTION_SCHEMA]], [[CONTENT_PIPELINE_SYNC|SYNC]], [[CONTENT_PIPELINE_RECONCILIACION|RECONCILIACION]] y `CARRUSEL-IG-TRADUCIDO.md` (Instalar-Home-Server).

## Problema

Una pieza se aprueba en dos propiedades: `Status = Listo` la manda a Postiz y `modo = programar` la deja publicarse. Para el equipo «Listo» significa «publícalo», y una réplica en `Listo` con `modo = borrador` no sale nunca sin que nadie lo note. En el calendario nadie ha usado `modo` en una fila hecha a mano: solo lo usan las réplicas, como visto bueno de una persona.

## Estrategia

`modo` y el estado `En Postiz (borrador)` se sustituyen por **un estado: `Por aprobar`**.

| `Status` | Quién lo escribe | Qué hace el sync |
|---|---|---|
| `Por aprobar` | la réplica, o una persona que quiere ver la pieza en Postiz antes de soltarla | la crea en Postiz como **borrador** (`type: draft`) dentro de la ventana de 15 días, y la fila **sigue en `Por aprobar`** |
| `Listo` | una persona: es la aprobación | la crea como **programada** (`type: schedule`) y la pasa a `Programado` |

`Listo` siempre quiere decir «publícalo». Si la pieza está en Postiz o no lo dice `❌ postiz_post_id`, no el estado.

### Invariantes que no se pueden romper

1. **Nada que no esté en `Listo` o `Programado` se crea como `schedule`.** Es la única forma de publicar.
2. **Ningún camino automático escribe `Listo` en una fila que estaba en `Por aprobar`**: sería aprobar sin una persona. Hoy la retirada escribe `Listo` en la fila aplazada a más de 15 días y en la recuperación por identidad; para una fila en `Por aprobar` ha de conservar `Por aprobar`.
3. La recuperación nunca juzga una fila en `Por aprobar` (un borrador no se publica). La «aprobada tarde» se detecta igual que hoy: fila en `Listo`/`Programado` cuyo post en Postiz sigue en `DRAFT` con la `Fecha` pasada → `Error`.
4. La réplica (`planificar.py`) crea sus filas en `Por aprobar` y reprograma al siguiente lunes las `Por aprobar` con la `Fecha` pasada. Nunca escribe `Listo`.
5. Los mensajes de `❌ error_log` que dicen «vuelve a poner Listo» no pueden empujar a aprobar sin querer una pieza que no estaba aprobada.

## Orden del corte en producción

El orden evita que exista en algún momento una fila en `Listo` sin aprobar mientras corre el sync nuevo:

1. Notion: añadir la opción `Por aprobar` a `Status` (inocuo para el sync actual, que no la lee).
2. Desplegar la réplica nueva con su `deploy.sh`, sin una réplica en curso: desde aquí las réplicas nacen en `Por aprobar`. `planificar.py` y la skill `replicar-carrusel` (que es quien escribe el estado final) cambian juntas, porque el `git pull` del clon va antes de copiar `planificar.py`. Nunca una sin la otra: `planificar.py` nuevo con la skill vieja deja una réplica en `Listo` sin `modo`, y el sync actual la publicaría.
3. Migrar filas: `En Postiz (borrador)`+`borrador` y `Listo`+`borrador` → `Por aprobar`; `En Postiz (borrador)`+`programar` (aprobada, aún sin sincronizar) → `Listo`; `Error`+`borrador` → se queda en `Error`.
4. Actualizar en n8n el sync, el subflow y la retirada; exportar sus copias.
5. Batería de pruebas (actualizada) en verde.
6. Notion: quitar la opción `En Postiz (borrador)` y la propiedad `modo`; ajustar la vista ▶ Publicar en IG, la descripción de `Status` y el manual.

**Vuelta atrás** (hasta el paso 6): reimportar las exportaciones anteriores de los workflows (`/opt/homeserver/n8n-workflows/`, se guardan aparte antes del paso 4), revertir `planificar.py` y devolver las filas con el mapeo inverso.

## Riesgos

- **María trabaja en el calendario a la vez.** La migración solo toca las filas que lo necesitan y se mira el estado justo antes.
- **Una fila en `Error` que venía de una réplica sin aprobar**: al corregirla, la persona elige `Por aprobar` o `Listo`. Lo dice el manual.
- **Los crons** (05:00 réplica, 06:00 sync, 06:20 retirada) no caen dentro del corte.
