# zfm_app/extensions.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text



db = SQLAlchemy()
bcrypt = Bcrypt()
migrate = Migrate()
scheduler = BackgroundScheduler(daemon=True)

def init_extensions(app):
    # DB/Bcrypt/Migrate
    db.init_app(app)
    bcrypt.init_app(app)
    migrate.init_app(app, db)

def register_cli(app):
    @app.cli.command("init-db")
    def init_db_cmd():
        """Cria as tabelas iniciais (DEV/MVP). Para produção: use flask db upgrade."""
        with app.app_context():
            # sanity check
            db.session.execute(text("SELECT 1"))
            db.create_all()
            print("Tabelas criadas.")
