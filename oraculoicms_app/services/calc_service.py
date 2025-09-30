# zfm_app/services/calc_service.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import current_app
from calc import MotorCalculo

def init_motor(app):
    # em produção, init_sheets preenche; em teste podemos ter skipado
    matrices = app.extensions.get("matrices") or {"rules": [], "sources": [], "version": "unknown"}
    # se você tem uma classe Motor, injete aqui:
    # app.extensions["motor"] = Motor(matrices)
    # ou, se for um dicionário/namespace:
    app.extensions["motor"] = {"matrices": matrices}

def get_motor():
    return current_app.extensions["motor"]

def rebuild_motor():
    """Reconstrói o motor após reload das planilhas."""
    matrices = current_app.extensions["matrices"]
    current_app.extensions["motor"] = MotorCalculo(matrices)
    return current_app.extensions["motor"]
