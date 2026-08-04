# Diagramas — pipeline Notion → n8n → Postiz → Instagram

> **Qué es esto:** el mapa visual de la automatización descrita en
> [CONTENT_PIPELINE_NOTION_POSTIZ.md](./CONTENT_PIPELINE_NOTION_POSTIZ.md).
> Ese documento explica **por qué** cada cosa es como es; éste enseña **cómo encaja**.
>
> **Fecha:** 2026-08-04 · refleja lo que está desplegado y activo.
> Si un diagrama y el sistema no coinciden, manda el sistema — y hay que corregir el diagrama.

---

## 1. Las cuatro piezas y quién manda

```mermaid
flowchart LR
    EQUIPO["👤 Equipo<br/>escribe copy, arrastra el fichero,<br/>marca publicación = Listo"]

    subgraph NOTION["NOTION · fuente de verdad"]
        CAL[("Calendario Social Media<br/>11 propiedades del pipeline")]
    end

    subgraph N8N["n8n · orquestador, sin estado propio"]
        A["Sync<br/>cron 06:00 + botón"]
        B["Subflow<br/>una fila"]
        D["Retirada y recuperación<br/>cron 06:20"]
        C["Receptor de estado"]
    end

    subgraph POSTIZ["POSTIZ · ejecutor y caché"]
        API["API pública v1"]
        TEMP["Temporal<br/>postWorkflowV106"]
        DISCO[("/uploads<br/>Seagate")]
    end

    IG["📷 Instagram<br/>3 cuentas standalone"]

    EQUIPO --> CAL
    CAL -->|"lee la cola"| A
    A -->|"una fila cada vez"| B
    B -->|"crea, borra, sube"| API
    B -->|"write-back"| CAL
    D -->|"compara y retira"| API
    D -->|"corrige estados"| CAL
    API --> DISCO
    API --> TEMP
    TEMP -->|"publica"| IG
    TEMP -->|"webhook al terminar"| C
    C -->|"Publicado / Error"| CAL

    style NOTION fill:#2d3748,stroke:#63b3ed,color:#fff
    style POSTIZ fill:#2d3748,stroke:#f6ad55,color:#fff
    style N8N fill:#2d3748,stroke:#68d391,color:#fff
```

**La regla que sostiene todo:** las flechas hacia Notion salen **sólo de n8n**.
Postiz nunca escribe en Notion. Dos escritores serían ninguna verdad.

---

## 2. El planificador — `eKxZPM4zjwhNb3vf`

Tres disparadores, un solo camino. El botón **no** manda una fila: relee la cola entera,
igual que el cron. Una sola implementación no puede divergir de sí misma.

```mermaid
flowchart TD
    CRON["⏰ Cron 06:00 Madrid"]
    WH1["🔗 Webhook postiz-sync-ig<br/>cabecera X-Sync-Token"]
    WH2["🔗 Webhook ruta secreta<br/>para el botón de Notion"]

    LEER["Notion: leer cola<br/>filtro: Plataforma=Instagram<br/>Y publicación no vacía"]
    PLAN{{"Planificar<br/>puertas y validaciones"}}

    CRON --> LEER
    WH1 --> LEER
    WH2 --> LEER
    LEER --> PLAN

    PLAN -->|"crear · recrear"| LOOP["Recorrer filas<br/>batch = 1"]
    PLAN -->|"ERROR"| MARCAR["Notion: marcar Error<br/>publicación=Error + motivo"]
    PLAN -->|"ignorar · fuera de ventana<br/>saltar · no tocar"| NADA["Sin acción"]

    LOOP --> SUB["Ejecutar subflow<br/>espera a que termine"]
    SUB --> LOOP

    style PLAN fill:#553c9a,stroke:#b794f4,color:#fff
    style MARCAR fill:#742a2a,stroke:#fc8181,color:#fff
```

### Las puertas de `Planificar`, en orden

El **orden importa**: las validaciones estructurales van antes que la ventana y el margen.
Si no, una fila sin hora se parsea como medianoche UTC, cae dentro del margen de 2 h
y sale como «saltar» en vez de `Error` — lo contrario de la regla.

```mermaid
flowchart TD
    START(["fila de Notion"]) --> P1{"publicación<br/>= Publicado?"}
    P1 -->|sí| NT["no tocar jamás"]
    P1 -->|no| P2{"estado vivo?<br/>Listo · Programado<br/>En Postiz borrador"}
    P2 -->|no| IG1["ignorar"]

    P2 -->|sí| V["Validaciones estructurales<br/>· Fecha con hora y offset<br/>· cuenta con integration.id<br/>· content no vacío<br/>· 1 a 10 assets<br/>· colaboradores: ni carrusel ni story"]
    V -->|"algo falla"| ERR["ERROR + motivo"]

    V -->|"todo bien"| W{"fecha > hoy+15d?"}
    W -->|sí| FV["fuera de ventana"]
    W -->|no| PA{"fecha ya pasó?"}
    PA -->|"sí, con post creado"| REC["ignorar<br/>lo revisa la recuperación"]
    PA -->|"sí, sin post"| ERR
    PA -->|no| M{"fecha < ahora+2h?"}
    M -->|sí| SALT["saltar<br/>margen de seguridad"]
    M -->|no| CR{"tiene postiz_post_id?"}
    CR -->|no| CREAR["crear"]
    CR -->|sí| RECREAR["recrear"]

    style V fill:#2c5282,stroke:#63b3ed,color:#fff
    style ERR fill:#742a2a,stroke:#fc8181,color:#fff
    style CREAR fill:#22543d,stroke:#68d391,color:#fff
    style RECREAR fill:#22543d,stroke:#68d391,color:#fff
```

---

## 3. El subflow de una fila — `A0XMq6dLdAWvwMPv`

Aquí es donde se mueve todo. **Los bytes nunca pasan por n8n**: se le manda a Postiz
la URL firmada de Notion y él la descarga por streaming.

```mermaid
flowchart TD
    INI(["Inicio<br/>datos de una fila"]) --> RELEER["Notion: releer fila<br/>URL del asset FRESCA<br/>caducan en 1 hora"]
    RELEER --> PREP["Preparar<br/>decide qué hay que hacer"]

    PREP --> QDEL{"¿borrar<br/>anterior?"}
    QDEL -->|"tiene postiz_post_id"| DEL["Postiz: DELETE post anterior"]
    DEL --> TRAS["Tras borrar<br/>ignora el cuerpo: siempre dice error:true"]
    QDEL -->|no| QUP
    TRAS --> QUP{"¿subir<br/>assets?"}

    QUP -->|"postiz_media vacío<br/>o no cuadra"| EXP["Expandir assets<br/>un item por fichero"]
    EXP --> UP["Postiz: upload-from-url<br/>por streaming"]
    UP --> REC["Recolectar media<br/>respeta el ORDEN"]
    REC --> GM["Notion: guardar postiz_media<br/>ESCRITURA 1"]
    GM --> MS["Media subida"]

    QUP -->|"reutilizable"| MR["Media reutilizada<br/>no se resube nada"]

    MS --> CONS["Construir POST<br/>__type=instagram-standalone"]
    MR --> CONS
    CONS --> POST["Postiz: POST /posts"]

    POST -->|"201"| RES["Resultado"]
    RES --> GID["Notion: guardar post_id y estado<br/>ESCRITURA 2"]

    POST -->|"error"| FE["Formatear error"]
    UP -->|"error"| FES["Formatear error de subida"]
    FE --> ME["Notion: marcar Error"]
    FES --> ME
    ME --> EXPH["Expandir media huérfano"]
    EXPH --> DELM["Postiz: DELETE media huérfano"]

    style UP fill:#2c5282,stroke:#63b3ed,color:#fff
    style GM fill:#22543d,stroke:#68d391,color:#fff
    style GID fill:#22543d,stroke:#68d391,color:#fff
    style ME fill:#742a2a,stroke:#fc8181,color:#fff
    style DELM fill:#742a2a,stroke:#fc8181,color:#fff
```

**Por qué dos escrituras y no una.** Guardar `postiz_media` en cuanto sube hace el proceso
reanudable: si algo falla después, el reintento **no vuelve a mover el fichero**.

**Por qué se borra el media al fallar.** La limpieza automática sólo hace candidato lo que
aparece en un post *publicado*. Un fichero subido y nunca publicado no lo recoge nadie —
ni a los 30 días ni nunca. Se borra **sólo si se subió en esa misma pasada**: si venía
reutilizado, borrarlo dejaría `postiz_media` apuntando a la nada.

---

## 4. Retirada y recuperación — `rxVcGlxSZjzzI5ez`

Reconciliar no es sólo crear lo que falta: es **retirar lo que ya no debe existir**.
Va 20 minutos después del sync para que los `postiz_post_id` ya estén escritos.

```mermaid
flowchart TD
    CR["⏰ Cron 06:20 Madrid"] --> GP["Postiz: GET ventana<br/>de hoy-30d a hoy+15d"]
    WM["🔗 Webhook manual"] --> GP
    GP --> GN["Notion: filas vivas<br/>toda fila con publicación puesta"]
    GN --> RECON{{"Reconciliar"}}

    RECON -->|"post que nadie reclama"| QR["¿retirar?"]
    RECON -->|"fila Programado<br/>con fecha pasada"| QREC["¿recuperar?"]
    RECON -->|"nada"| NN["Nada que hacer"]

    QR --> DP["Postiz: DELETE post huérfano"]
    QREC --> CE["Notion: corregir estado<br/>Publicado o Error"]

    style RECON fill:#553c9a,stroke:#b794f4,color:#fff
    style DP fill:#742a2a,stroke:#fc8181,color:#fff
```

### Los tres filtros que evitan un desastre

```mermaid
flowchart LR
    P(["post en la ventana"]) --> F1{"creationMethod<br/>= API?"}
    F1 -->|"WEB · hecho a mano"| S1["NO TOCAR"]
    F1 -->|sí| F2{"state<br/>QUEUE o DRAFT?"}
    F2 -->|"PUBLISHED · ERROR"| S2["NO TOCAR"]
    F2 -->|sí| F3{"publica dentro<br/>de 2 h?"}
    F3 -->|sí| S3["NO TOCAR<br/>margen de seguridad"]
    F3 -->|no| F4{"alguna fila de Notion<br/>lo reclama?"}
    F4 -->|sí| S4["NO TOCAR"]
    F4 -->|no| DEL["retirar"]

    style S1 fill:#22543d,stroke:#68d391,color:#fff
    style DEL fill:#742a2a,stroke:#fc8181,color:#fff
```

> **El primer filtro no es cosmético.** Un post creado desde la UI de Postiz no tiene fila
> en Notion, así que «borrar todo lo que nadie reclama» se lo llevaría. Cuando se auditó
> había uno real programado para agosto. Sin ese filtro, la primera pasada del cron
> lo habría borrado.

---

## 5. El receptor de estado — `VMezjZaMTIU5dIUz`

Postiz manda el webhook **sin ninguna cabecera de autenticación**, así que el secreto
va en la ruta. Y la regla de lectura no es la obvia.

```mermaid
flowchart TD
    WH["🔗 Webhook ruta secreta<br/>lo llama post.activity.ts"] --> INT{{"Interpretar payload"}}

    INT -->|"cuerpo vacío []"| IGN["ignorar<br/>post borrado o v1.0.5"]
    INT -->|"releaseURL o releaseId<br/>CON valor"| PUB["Publicado<br/>+ release_url"]
    INT -->|"sin releaseURL<br/>y state=ERROR"| ERR["Error + motivo"]
    INT -->|"QUEUE u otro"| IGN

    PUB --> BUS["Notion: buscar fila<br/>por postiz_post_id"]
    ERR --> BUS
    BUS --> RES{"¿fila<br/>encontrada?"}
    RES -->|"1 fila"| ESC["Notion: escribir estado"]
    RES -->|"0 o varias"| SF["Sin fila que actualizar"]

    style INT fill:#553c9a,stroke:#b794f4,color:#fff
    style ESC fill:#22543d,stroke:#68d391,color:#fff
```

> ### ⚠️ `releaseURL` manda sobre `state`
> Si falla el primer comentario —donde van los hashtags—, Postiz marca el post padre como
> `ERROR` **pero conserva el permalink**: Instagram ya lo tiene publicado.
>
> Con la regla ingenua «`state=ERROR` ⇒ no publicó», la fila iría a `Error`, alguien la
> devolvería a `Listo` y el sync la recrearía: **segunda publicación en Instagram**.

---

## 6. La propiedad `publicación`, estado a estado

Sólo hay una transición que escribe una persona: **`Listo`**. Todo lo demás lo pone n8n.

```mermaid
stateDiagram-v2
    [*] --> Vacio: fila nueva
    Vacio: (vacío)

    Vacio --> Listo: 👤 el equipo aprueba
    Listo --> Programado: 🤖 sync · modo=programar
    Listo --> EnPostiz: 🤖 sync · modo=borrador
    EnPostiz: En Postiz (borrador)

    Programado --> Publicado: 🤖 webhook o recuperación
    Programado --> Error: 🤖 falló la publicación
    Listo --> Error: 🤖 no pasó las validaciones
    EnPostiz --> Programado: 🤖 al cambiar modo

    Error --> Listo: 👤 se corrige y se reenvía
    Programado --> Vacio: 👤 retira la pieza
    Listo --> Vacio: 👤 se arrepiente

    Publicado --> [*]: no se toca jamás

    note right of Vacio
        Vaciarlo retira el post de Postiz
        en la pasada de retirada
    end note
    note right of Publicado
        Estado terminal.
        Ni el sync ni la retirada lo tocan.
    end note
```

---

## 7. Un día cualquiera, en orden

```mermaid
sequenceDiagram
    autonumber
    participant E as 👤 Equipo
    participant N as Notion
    participant S as n8n · sync
    participant R as n8n · retirada
    participant P as Postiz
    participant T as Temporal
    participant I as Instagram
    participant W as n8n · receptor

    E->>N: escribe copy, arrastra el reel,<br/>pone fecha y marca Listo
    Note over E,N: puede pulsar el botón y no esperar al cron

    S->>N: 06:00 · lee la cola
    N-->>S: filas con publicación puesta
    S->>N: pide la URL FRESCA del asset
    S->>P: POST /upload-from-url (sólo la URL)
    P->>N: descarga el fichero por streaming
    S->>N: escribe postiz_media
    S->>P: POST /posts
    P-->>S: postId
    S->>N: postiz_post_id + publicación=Programado
    P->>T: arranca postWorkflowV106

    R->>P: 06:20 · GET ventana
    R->>N: filas vivas
    Note over R: borra sólo lo creado por API<br/>que nadie reclama

    T->>T: duerme hasta la hora
    T->>I: publica
    I-->>T: permalink
    T->>W: webhook con el post completo
    W->>N: publicación=Publicado + release_url
```

---

## 8. Qué pasa cuando algo falla, y quién lo recoge

| Falla | Lo detecta | La fila acaba en | ¿Se limpia? |
|---|---|---|---|
| Validación previa (sin hora, >10 assets, colaboradores en carrusel…) | `Planificar` | `Error` + motivo | No se subió nada |
| El asset no se puede descargar o pasa de 1 GiB | `upload-from-url` → 400 | `Error` + motivo de Postiz | No llegó a crearse media |
| `POST /posts` rechazado (copy largo, media inválido…) | subflow | `Error` + motivo | **Borra el media que acaba de subir** |
| Instagram rechaza al publicar | `postWorkflowV106` | `Error` vía webhook | El media sobrevive para el reintento |
| Falla el primer comentario tras publicar | receptor | **`Publicado`** + aviso | — |
| n8n caído cuando Postiz publica | pasada de recuperación 06:20 | `Publicado` o `Error` | — |
| Token de Instagram caducado | `refreshNeeded` → webhook | `Error` | — |
| Notion caído a las 06:00 | *nadie* | queda como estaba | ⚠️ **decisión abierta** |

```mermaid
flowchart LR
    F(["algo falla"]) --> Q1{"¿el webhook<br/>llegó?"}
    Q1 -->|sí| INST["Notion se entera<br/>al instante"]
    Q1 -->|"no · entrega best-effort<br/>sin reintento"| Q2{"¿la fecha<br/>ya pasó?"}
    Q2 -->|sí| REC["la recuperación de las 06:20<br/>lo corrige"]
    Q2 -->|no| ESP["sigue en Programado<br/>hasta que pase la fecha"]

    style INST fill:#22543d,stroke:#68d391,color:#fff
    style REC fill:#2c5282,stroke:#63b3ed,color:#fff
```

**El webhook es el camino rápido, no el único.** Su entrega es best-effort: `post.activity.ts`
envuelve el `fetch` en un `try/catch` vacío. Por eso existe la pasada de recuperación —
y por eso no se puede eliminar el polling del todo.

---

## 9. Dónde vive cada cosa

```mermaid
flowchart TD
    subgraph GIT["📦 En git · custom/postiz-dc"]
        G1["post.workflow.v1.0.6.ts<br/>webhook en todo camino terminal"]
        G2["posts.repository.ts<br/>releaseId + error en el payload"]
        G3["public.integrations.controller.ts<br/>DELETE /media/:id · upload por streaming"]
        G4["local.storage.ts + upload.interface.ts<br/>uploadStream opcional"]
        G5["docs/architecture/*.md"]
    end

    subgraph SRV["🖥️ Sólo en el Beelink"]
        S1["/opt/homeserver/n8n-workflows/<br/>los 4 workflows exportados · modo 600"]
        S2["/opt/homeserver/.env<br/>tokens y rutas secretas"]
        S3["/opt/homeserver/postiz/postiz.env<br/>API_LIMIT · MAX_URL_UPLOAD_BYTES"]
        S4[("/mnt/seagate/postiz-media<br/>bind mount de /uploads")]
    end

    subgraph EXT["☁️ Fuera del repo"]
        E1["n8n · 4 workflows activos"]
        E2["Notion · 11 propiedades + 2 vistas + botón"]
        E3["Postiz · webhook registrado"]
    end

    style GIT fill:#22543d,stroke:#68d391,color:#fff
    style SRV fill:#744210,stroke:#f6ad55,color:#fff
    style EXT fill:#2c5282,stroke:#63b3ed,color:#fff
```

> **Los workflows no van a git a propósito.** Dos de ellos llevan rutas secretas dentro,
> y esto es un fork de un proyecto público: basta un push al remoto equivocado.
> La copia durable está en el servidor, con permisos `600`.

---

## 10. Los identificadores, de un vistazo

| Objeto | ID |
|---|---|
| Sync (cron 06:00 + botón) | `eKxZPM4zjwhNb3vf` |
| Subflow (una fila) | `A0XMq6dLdAWvwMPv` |
| Retirada y recuperación (cron 06:20) | `rxVcGlxSZjzzI5ez` |
| Receptor de estado | `VMezjZaMTIU5dIUz` |
| Calendario de Notion | `186a2405-a123-81dc-832f-000b82a65c0c` |
| Organización de Postiz | `30c506a6-0a2c-4661-95bb-abec2e14b3f2` |
| Dustin Calderón (IG) | `cmqjq77hg0001mw7y2xf6bg86` |
| CITEM (IG) | `cmqjqapu00003mw7yrudcwklj` |
| AMORISMO VOL III (IG) | `cmqjqfvnw0005mw7yoywgo6he` |

Las rutas secretas de los webhooks **no se escriben aquí**: viven en `/opt/homeserver/.env`
como `N8N_POSTIZ_WEBHOOK_PATH` y `N8N_SYNC_IG_BUTTON_PATH`.
