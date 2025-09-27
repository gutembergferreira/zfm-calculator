# zfm_app/services/calc_service.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import current_app
from calc import MotorCalculo

def init_motor(app):
    matrices = app.extensions["matrices"]  # setado em init_sheets
    motor = MotorCalculo(matrices)
    app.extensions["motor"] = motor

def get_motor():
    return current_app.extensions["motor"]

def rebuild_motor():
    """Reconstrói o motor após reload das planilhas."""
    matrices = current_app.extensions["matrices"]
    current_app.extensions["motor"] = MotorCalculo(matrices)
    return current_app.extensions["motor"]
