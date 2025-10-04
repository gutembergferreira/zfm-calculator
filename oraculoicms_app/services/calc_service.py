# zfm_app/services/calc_service.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import current_app
from calc import MotorCalculo

def _build_engine(app):
    """Constrói o engine a partir das matrices já carregadas no app."""
    matrices = app.extensions.get("matrices") or {}  # dict esperado pelo MotorCalculo
    return MotorCalculo(matrices)

def init_motor(app):
    """
    Inicializa o motor na inicialização da aplicação.
    IMPORTANTE: isso deve rodar DEPOIS de app.extensions["matrices"] existir.
    """
    app.extensions["motor"] = _build_engine(app)

def get_motor():
    """
    Retorna SEMPRE um objeto com .calcula_st (nunca um dict).
    Se por algum motivo houver um dict antigo em extensions, reconstrói.
    """
    eng = current_app.extensions.get("motor")
    if eng is None or isinstance(eng, dict):
        eng = _build_engine(current_app)
        current_app.extensions["motor"] = eng
    return eng

def rebuild_motor():
    """Reconstrói o motor após reload das planilhas."""
    eng = _build_engine(current_app)
    current_app.extensions["motor"] = eng
    return eng
