# tests/test_sheets_service.py
from __future__ import annotations

import types
import pytest

from oraculoicms_app.services.sheets_service import (
    init_sheets, get_sheet_client, get_matrices, reload_matrices
)


@pytest.fixture
def clear_env(monkeypatch):
    """Garante que as flags de controle não interfiram entre testes."""
    for k in ("DISABLE_SHEETS", "SKIP_SHEETS"):
        monkeypatch.delenv(k, raising=False)
    yield


def test_init_sheets_disabled_in_testing(app, clear_env, caplog):
    # app fixture já vem com TESTING=True
    with app.app_context():
        init_sheets(app)
        assert app.extensions.get("sheet_client") is None
        assert app.extensions.get("matrices") == {}
        # helpers devem refletir o estado
        assert get_sheet_client() is None
        assert get_matrices() == {}


def test_init_sheets_skip_via_env(app, clear_env, monkeypatch):
    # Simula ambiente não-test, porém com SKIP_SHEETS=1
    app.config["TESTING"] = False
    monkeypatch.setenv("SKIP_SHEETS", "1")

    # cria um SheetClient fake só para checar que no final ele fica None
    class FakeClient:
        worksheets = ["Aba1", "Aba2"]
        def matrices(self): return {"M": 1}

    # Garantia: mesmo que exista SheetClient, a flag deve zerar
    import sheets as sheets_mod  # seu módulo real
    monkeypatch.setattr(sheets_mod, "SheetClient", FakeClient, raising=True)

    with app.app_context():
        init_sheets(app)
        assert app.extensions.get("sheet_client") is None
        # quando pula por SKIP_SHEETS, o código preenche 'worksheets' (não 'matrices')
        assert app.extensions.get("worksheets") == []


def test_init_sheets_graceful_on_misconfig(app, clear_env, monkeypatch, caplog):
    # Sem TESTING e sem SKIP/DISABLE => executa bloco try/except
    app.config["TESTING"] = False

    import sheets as sheets_mod
    # Força o construtor a levantar SheetMisconfig
    class Boom(sheets_mod.SheetMisconfig): pass
    def boom_client(*a, **k):
        raise Boom("faltou SPREADSHEET_ID")

    monkeypatch.setattr(sheets_mod, "SheetClient", boom_client, raising=True)

    with app.app_context():
        init_sheets(app)
        # deve continuar sem falhar e desligar Sheets
        assert app.extensions.get("sheet_client") is None
        assert app.extensions.get("matrices") == {}
        # log de warning foi emitido
        assert any("Sheets não configurado corretamente" in m for m in caplog.text.splitlines())


def test_reload_matrices_uses_client(app):
    # Prepara um client fake com matrices()
    class FakeClient:
        def __init__(self): self.calls = 0
        def matrices(self):
            self.calls += 1
            return {"K": 42, "calls": self.calls}

    with app.app_context():
        # injeta client e estado inicial
        app.extensions["sheet_client"] = FakeClient()
        app.extensions["matrices"] = {}

        out1 = reload_matrices()
        assert out1 == {"K": 42, "calls": 1}
        assert get_matrices() == {"K": 42, "calls": 1}

        out2 = reload_matrices()
        assert out2["calls"] == 2  # foi chamado novamente
