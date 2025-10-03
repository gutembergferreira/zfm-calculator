# oraculoicms_app/services/sheets_service.py
from __future__ import annotations
import os
from flask import current_app
from sheets import SheetMisconfig, SheetClient  # tipo da exceção do teu package

def init_sheets(app):
    """
    Inicializa o cliente de Google Sheets (quando configurado).
    Em TESTING/CI ou se flags de skip estiverem setadas, não inicializa.
    Em misconfig (SheetMisconfig), NÃO levanta erro — apenas loga e segue sem Sheets.
    """
    # Inicializa chaves para evitar KeyError em qualquer branch
    app.extensions.setdefault("sheet_client", None)
    app.extensions.setdefault("matrices", {})
    app.extensions.setdefault("worksheets", [])

    # 1) Desabilitado por TESTING/CI
    if app.config.get("TESTING") or os.getenv("DISABLE_SHEETS") == "1":
        app.logger.info("Sheets desabilitado (TESTING/CI).")
        return

    # 2) Desabilitado explicitamente
    if getattr(app, "testing", False) or os.getenv("SKIP_SHEETS") == "1":
        return

    # 3) Tenta inicializar de fato
    try:
        from sheets import SheetClient
        client = SheetClient()
        # matrices(): alguns clients retornam dict; se não houver, cai para {}
        matrices = getattr(client, "matrices", lambda: {})()
        worksheets = getattr(client, "worksheets", [])

        app.extensions["sheet_client"] = client
        app.extensions["matrices"] = matrices if isinstance(matrices, dict) else {}
        app.extensions["worksheets"] = worksheets
        return
    except SheetMisconfig as e:
        # Em misconfig, não quebrar a app/testes: apenas logar e seguir sem client.
        app.logger.warning(f"Sheets não configurado corretamente: {e}. Continuando sem Sheets.")
        app.extensions["sheet_client"] = None
        app.extensions["matrices"] = {}
        app.extensions["worksheets"] = []
        return


def get_sheet_client():
    # mais robusto se a extensão não existir em algum contexto
    return current_app.extensions.get("sheet_client")


def get_matrices():
    return current_app.extensions.get("matrices", {})


def reload_matrices():
    """Recarrega matrices no app.extensions (após updater)."""
    sc = get_sheet_client()
    if sc is None:
        current_app.extensions["matrices"] = {}
        return {}
    matrices = getattr(sc, "matrices", lambda: {})()
    current_app.extensions["matrices"] = matrices if isinstance(matrices, dict) else {}
    return current_app.extensions["matrices"]
