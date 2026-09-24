# -*- coding: utf-8 -*-
"""Historial de errores del pipeline Notion → Postiz, leído de n8n. Solo lectura.

`❌ error_log` guarda el último error de cada fila y el sync lo vacía al salir
bien: el historial solo existe en las ejecuciones de n8n, las de los últimos 90
días (docs/guides/CONTENT_PIPELINE_OPERACION.md §3). Este script lo saca, una línea por
error, con la fecha, de dónde viene y el motivo.

    python3 errores-pipeline.py            # en el Beelink; sin las filas de la suite
    python3 errores-pipeline.py --todo     # con ellas

Columnas: fecha · origen · ejecución · fila o post · motivo. Orígenes:
  SYNC        validación de `Planificar` (la fila no pasa)
  SUBFLOW     `Formatear error` / `Formatear error de subida` (Postiz o la subida)
  RECEPTOR    Postiz avisó de que no publicó
  RECUPERA    la recuperación (06:20 y en cada sync) corrigió un estado
  EJECUCION   el workflow entero falló (token, red): no llegó a escribir en Notion

Depende del formato interno de n8n (`execution_data.data` en flatted, con
`resultData.runData`) y de los nombres de nodo. Si una versión nueva de n8n lo
cambia, el script lo dice (NO_LEGIBLE) en vez de devolver una lista vacía.
"""
import json, subprocess, sys

SUITE = "__ZZ suite"


def psql(q):
    return subprocess.check_output(["docker", "exec", "postgres_core", "psql", "-U", "postgres",
                                    "-d", "n8n_db", "-At", "-F", "\x1f", "-c", q]).decode()


def flatted(texto):
    """n8n guarda la ejecución con `flatted`: una lista donde cada cadena que es un
    número apunta a otra posición de la lista."""
    arr = json.loads(texto)
    memo = {}

    def rev(i):
        if i in memo:
            return memo[i]
        v = arr[i]
        ref = lambda x: rev(int(x)) if isinstance(x, str) and x.isdigit() else x  # noqa: E731
        if isinstance(v, dict):
            memo[i] = o = {}
            o.update({k: ref(x) for k, x in v.items()})
            return o
        if isinstance(v, list):
            memo[i] = o = []
            o.extend(ref(x) for x in v)
            return o
        memo[i] = v
        return v
    return rev(0)


def salida(run, nodo):
    for r in run.get(nodo) or []:
        for rama in (r.get("data") or {}).get("main") or []:
            for it in rama or []:
                yield it.get("json", {})


def errores(run, wf):
    if wf.startswith("Postiz · Sync Instagram"):
        for j in salida(run, "Planificar"):
            if j.get("accion") == "ERROR":
                yield "SYNC", j.get("name") or "", j.get("error_log") or ""
    elif "SUBFLOW" in wf:
        fila = next((j.get("name") or "" for j in salida(run, "Inicio")), "")
        for nodo in ("Formatear error", "Formatear error de subida"):
            for j in salida(run, nodo):
                yield "SUBFLOW", fila, j.get("error_log") or ""
    elif "Receptor" in wf:
        for j in salida(run, "Interpretar payload"):
            if j.get("accion") == "escribir" and j.get("estado") == "Error":
                yield "RECEPTOR", j.get("postiz_post_id") or "", j.get("error_log") or ""
    elif "Retirada" in wf:
        for j in salida(run, "Reconciliar"):
            if j.get("tipo") == "recuperar":
                yield "RECUPERA", j.get("page_id") or "", "%s: %s" % (j.get("estado"), j.get("error_log") or "")


def main():
    todo = "--todo" in sys.argv
    filas = psql("""SELECT e.id, w.name, e.status,
                           to_char(e."startedAt" AT TIME ZONE 'Europe/Madrid', 'YYYY-MM-DD HH24:MI'), d.data
                    FROM execution_entity e JOIN workflow_entity w ON w.id = e."workflowId"
                    JOIN execution_data d ON d."executionId" = e.id
                    WHERE w.name LIKE 'Postiz%' ORDER BY e."startedAt";""")
    for linea in filas.splitlines():
        if not linea.strip():
            continue
        eid, wf, estado, cuando, datos = linea.split("\x1f", 4)
        try:
            resultado = flatted(datos)["resultData"]
            run = resultado["runData"]
        except Exception as e:  # noqa: BLE001 — se informa, no se esconde
            print("\t".join([cuando, "NO_LEGIBLE", eid, wf, repr(e)[:120]]))
            continue
        for origen, fila, motivo in errores(run, wf):
            if todo or SUITE not in fila:
                print("\t".join([cuando, origen, eid, fila[:40], " ".join(motivo.split())[:300]]))
        if estado != "success":
            fallo = (resultado.get("error") or {}).get("message") or estado
            print("\t".join([cuando, "EJECUCION", eid, wf, " ".join(str(fallo).split())[:300]]))


if __name__ == "__main__":
    main()
