# zfm_app/__init__.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import Flask
from config import Config
from .blueprints.admin import admin_bp
from .extensions import db, bcrypt, migrate, scheduler, init_extensions, register_cli
from .services.sheets_service import init_sheets
from .services.calc_service import init_motor
from .blueprints.core import bp as core_bp
from .blueprints.auth import bp as auth_bp
from .blueprints.nfe import bp as nfe_bp

def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(config_object)

    # Extensões (DB/Bcrypt/Migrate/Scheduler)
    init_extensions(app)

    # Serviços (Sheets + Motor de cálculo) — ficam disponíveis em app.extensions
    init_sheets(app)        # app.extensions["sheet_client"], ["matrices"]
    init_motor(app)         # app.extensions["motor"]

    # Blueprints
    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(nfe_bp)

    # CLI (ex.: flask init-db)
    register_cli(app)

    # Scheduler (ex.: dia 1 às 03:00 — atualizador AM)
    if not scheduler.running:
        scheduler.start()

    return app
