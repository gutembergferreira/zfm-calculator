# tests/test_settings_service.py
from __future__ import annotations

import pytest

# importa o serviço e o modelo
from oraculoicms_app.services.settings import get_setting, set_setting
from oraculoicms_app.models.setting import Setting


def test_get_setting_returns_default_when_missing(app, db_session):
    with app.app_context():
        assert get_setting("pix_key", group="payments", default="") == ""
        assert get_setting("nao_existe", group="qualquer", default="DEFAULT") == "DEFAULT"


def test_set_then_get_creates_record(app, db_session):
    with app.app_context():
        # nada ainda
        assert db_session.query(Setting).count() == 0

        # cria
        set_setting("pix_key", "chave-abc", group="payments")

        # verifica que persistiu
        row = db_session.query(Setting).filter_by(group="payments", key="pix_key").first()
        assert row is not None
        assert row.value == "chave-abc"

        # get_setting deve retornar o valor salvo
        assert get_setting("pix_key", group="payments", default="x") == "chave-abc"


def test_set_setting_updates_existing_value(app, db_session):
    with app.app_context():
        set_setting("pix_key", "valor1", group="payments")
        assert get_setting("pix_key", group="payments") == "valor1"

        # atualiza
        set_setting("pix_key", "valor2", group="payments")
        assert get_setting("pix_key", group="payments") == "valor2"

        # garante que só há um registro para o par (group,key)
        rows = db_session.query(Setting).filter_by(group="payments", key="pix_key").all()
        assert len(rows) == 1


def test_groups_are_isolated(app, db_session):
    with app.app_context():
        # salva em dois grupos diferentes
        set_setting("pix_key", "pagamentos-123", group="payments")
        set_setting("pix_key", "webhooks-456", group="webhooks")

        # get_setting deve respeitar o group
        assert get_setting("pix_key", group="payments") == "pagamentos-123"
        assert get_setting("pix_key", group="webhooks") == "webhooks-456"


def test_set_setting_accepts_empty_and_unicode(app, db_session):
    with app.app_context():
        # vazio
        set_setting("pix_receiver", "", group="payments")
        assert get_setting("pix_receiver", group="payments", default="FALLBACK") == ""

        # unicode
        set_setting("pix_receiver", "Empresa Óráculo 🌟", group="payments")
        assert get_setting("pix_receiver", group="payments") == "Empresa Óráculo 🌟"
