# -*- coding: utf-8 -*-
"""Batería de pruebas del pipeline. Ejecuta las partes de `suite/` en orden y en un solo
espacio de nombres (cada parte ve lo que definieron las anteriores). Cada parte es una
responsabilidad: comun · disparadores · cuentas · camino · aprobacion · errores · identidad · mcp · reposo.

Antes de crear nada barre lo que dejó una suite anterior que muriera a medias, y al salir
borra lo suyo (suite/00-comun.py). Qué se necesita y cómo se lanza: CONTENT_PIPELINE_OPERACION.md §1."""
import glob, os

_aqui = os.path.dirname(os.path.abspath(__file__))
G = {"__name__": "suite"}
for _ruta in sorted(glob.glob(os.path.join(_aqui, "suite", "*.py"))):
    exec(compile(open(_ruta, encoding="utf-8").read(), _ruta, "exec"), G)
