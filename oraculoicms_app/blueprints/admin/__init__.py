# app/blueprints/admin/__init__.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import Blueprint

admin_bp = Blueprint("admin_bp", __name__, url_prefix="")

# importa rotas para registrar no blueprint
from . import routes  # noqa: E402,F401
