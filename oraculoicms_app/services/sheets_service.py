# zfm_app/services/sheets_service.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import current_app
from sheets import SheetClient

def init_sheets(app):
    """Cria SheetClient e carrega matrices uma vez no boot."""
    sheet_client = SheetClient()
    matrices = sheet_client.matrices()
    app.extensions["sheet_client"] = sheet_client
    app.extensions["matrices"] = matrices

def get_sheet_client():
    return current_app.extensions["sheet_client"]

def get_matrices():
    return current_app.extensions["matrices"]

def reload_matrices():
    """Recarrega matrices no app.extensions (após updater)."""
    sc = get_sheet_client()
    matrices = sc.matrices()
    current_app.extensions["matrices"] = matrices
    return matrices
