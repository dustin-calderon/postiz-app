# -*- coding: utf-8 -*-
"""Mapa integracion -> carpeta de cuenta del archivo de Drive (SSoT).

Lo lee tambien la bateria (suite/15-cuentas.py).
"""

# El nombre de la carpeta de cuenta se resuelve por integrationId, NO por
# Integration.name ni por la propiedad `cuenta` de Notion. Si no, el mismo canal
# genera dos carpetas: los posts hechos a mano dan "CITEM Conservatorio
# Iberoamericano..." y los del pipeline dan "CITEM", y el archivo de una cuenta
# queda partido en dos sitios. Son los mismos ids que usa el nodo Planificar.
CUENTAS = {
    "cmqjq77hg0001mw7y2xf6bg86": "Dustin Calderón",
    "cmqjqapu00003mw7yrudcwklj": "CITEM",
    "cmqjqfvnw0005mw7yoywgo6he": "AMORISMO VOL III",
    "cmx0fv5tn008opa54kuss6g8n": "Los Repertoristas",
    "cmx0iwc63008upa54z1bpbgg7": "Composición de teatro musical",
    "cmx0djkq4008mpa54tjg2um7f": "Merchicales",
    # 6ID y DCP se llaman en Postiz con letras decorativas de Unicode: sin
    # entrada aqui, el respaldo de abajo las pondria en el nombre de la carpeta.
    "cmx0h460l008qpa541x51l7zv": "6ID",
    "cmx0is2ma008spa54o9o7dgiz": "DCP Music Records",
    # TikTok. Se llama igual que la de Instagram ("Dustin Calderon"), asi que
    # sin un nombre distinto un cross-post generaria LA MISMA carpeta y el
    # segundo post machacaria los masters del primero.
    "cmqjs6xnx0001q07q9aohapuv": "Dustin Calderón (TikTok)",
}
