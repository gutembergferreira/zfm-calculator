# zfm_app/__init__.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os

from flask import Flask
from config import Config, TestingConfig, StagingConfig, ProductionConfig
from .blueprints.admin import admin_bp
from .extensions import db, bcrypt, migrate, scheduler, init_extensions, register_cli
from .services.sheets_service import init_sheets
from .services.calc_service import init_motor
from .blueprints.core import bp as core_bp
from .blueprints.auth import bp as auth_bp
from .blueprints.nfe import bp as nfe_bp
from .blueprints.files import bp as files_bp
from oraculoicms_app.blueprints.support import bp as support_bp
from oraculoicms_app.blueprints.support_admin import bp as support_admin_bp
from .blueprints.billing import bp as billing_bp
from datetime import datetime

def create_app(config_object: type[Config] = Config) -> Flask:


    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app_env = os.getenv("APP_ENV", "").lower()

    if app_env == "testing":
        app.config.from_object(TestingConfig)
    elif app_env == "staging":
        app.config.from_object(StagingConfig)
    elif app_env == "production":
        app.config.from_object(ProductionConfig)
    else:
        app.config.from_object(Config)

        # Extensões (DB/Bcrypt/Migrate/Scheduler)
    init_extensions(app)

    # Serviços (matrizes + motor de cálculo) — ficam disponíveis em app.extensions
    init_sheets(app)        # app.extensions["matrices"]
    init_motor(app)         # app.extensions["motor"]
    app.config["STARTED_AT"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Blueprints
    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(nfe_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(support_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(support_admin_bp)
    # CLI (ex.: flask init-db)
    register_cli(app)

    # Scheduler (ex.: dia 1 às 03:00 — atualizador AM)
    if not app.config.get("TESTING") and os.getenv("DISABLE_SCHEDULER") != "1":
        if not scheduler.running:
            scheduler.start()

    @app.template_filter("datetimeformat")
    def datetimeformat(value, fmt="%d/%m/%Y %H:%M"):
        import datetime
        return datetime.datetime.utcfromtimestamp(int(value)).strftime(fmt)
    return app
