# zfm_app/services/sheets_service.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import current_app
from sheets import SheetClient, SheetMisconfig
import os


def init_sheets(app):
    # Em CI/testes ou quando explicitamente desabilitado, não inicializa Sheets
    if app.config.get("TESTING") or os.getenv("DISABLE_SHEETS") == "1":
        app.logger.info("Sheets desabilitado (TESTING/CI).")
        app.extensions["sheet_client"] = None
        app.extensions["matrices"] = {}
        return
    try:
        client = SheetClient()
        matrices = client.get_matrices()
        app.extensions["sheet_client"] = client
        app.extensions["matrices"] = matrices
    except SheetMisconfig as e:
    # Em produção você pode querer falhar; mas em dev/CI ignoramos para não travar migrações/tests
        app.logger.warning(f"Sheets não configurado corretamente: {e}. Continuando sem Sheets.")
        app.extensions["sheet_client"] = None
        app.extensions["matrices"] = {}

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
