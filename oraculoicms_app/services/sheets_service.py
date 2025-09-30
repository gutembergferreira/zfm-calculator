# zfm_app/services/sheets_service.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import current_app
from sheets import SheetClient
import os


def init_sheets(app):
    # NÃO inicializa Sheets em testes ou quando pedirmos explicitamente
    if getattr(app, "testing", False) or os.getenv("SKIP_SHEETS") == "1":
        app.extensions["sheet_client"] = None
        app.extensions["worksheets"] = []
        return

    from sheets import SheetClient  # seu cliente real
    client = SheetClient()
    app.extensions["sheet_client"] = client
    # se você armazenava titles/abas:
    app.extensions["worksheets"] = getattr(client, "worksheets", [])

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
