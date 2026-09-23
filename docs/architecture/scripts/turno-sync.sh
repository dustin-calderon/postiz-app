#!/bin/sh
# turno-sync.sh — cuantas pasadas del sync, anteriores a una, siguen en marcha.
#
# Dos pasadas del sync a la vez deciden cada una con lo que leyeron al empezar
# y pueden pisarse: un Error con datos viejos encima del resultado de la otra,
# o una edicion que no llega a Postiz. El sync lo pregunta al empezar y espera
# mientras la respuesta no sea 0, asi que las pasadas van de una en una, en el
# orden en que llegaron (CONTENT_PIPELINE_NOTION_POSTIZ.md §9.1).
#
# Uso: turno-sync.sh <id de la ejecucion>
# Salida: un numero por stdout. Solo lee la base de n8n.
#
# Lo llama la clave SSH restringida de n8n (n8n-ssh-wrapper.sh), que solo le
# pasa un id numerico. Una ejecucion de mas de 30 minutos no cuenta: una pasada
# dura minutos, y una colgada o sin cerrar tras un reinicio no debe parar el
# sync para siempre.
#
# Copia viva: /opt/homeserver/postiz/turno-sync.sh.

set -eu

SYNC=eKxZPM4zjwhNb3vf

case "${1:-}" in
  ''|*[!0-9]*) echo "uso: turno-sync.sh <id numerico de la ejecucion>" >&2; exit 2 ;;
esac

docker exec postgres_core psql -U postgres -d n8n_db -Atq -v ON_ERROR_STOP=1 -c "
  SELECT count(*) FROM execution_entity
  WHERE \"workflowId\" = '$SYNC' AND id < $1
    AND status IN ('new', 'running', 'waiting')
    AND COALESCE(\"startedAt\", \"createdAt\") > now() - interval '30 minutes';"
