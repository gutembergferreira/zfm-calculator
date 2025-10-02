# tests/test_motor_service.py
from __future__ import annotations

import types
import builtins
import pytest

from oraculoicms_app.services.calc_service import init_motor, get_motor, rebuild_motor


def test_init_motor_uses_existing_matrices(app):
    """Quando já existe matrices no app.extensions, o init_motor deve usá-lo."""
    matrices = {"rules": [1, 2, 3], "sources": ["A"], "version": "v1"}
    app.extensions["matrices"] = matrices

    with app.app_context():
        init_motor(app)
        motor = get_motor()

    # init_motor coloca um dicionário {"matrices": <...>}
    assert isinstance(motor, dict)
    assert motor.get("matrices") is matrices  # mesmo objeto


def test_init_motor_uses_default_when_missing(app):
    """Sem matrices prévia, init_motor usa o default {'rules': [], 'sources': [], 'version': 'unknown'}."""
    # garante que não há matrices prévia
    app.extensions.pop("matrices", None)

    with app.app_context():
        init_motor(app)
        motor = get_motor()

    assert isinstance(motor, dict)
    m = motor.get("matrices")
    assert isinstance(m, dict)
    assert m.get("rules") == []
    assert m.get("sources") == []
    assert m.get("version") == "unknown"
