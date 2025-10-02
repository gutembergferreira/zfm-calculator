# config.py
# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv
load_dotenv()
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    FLASK_ENV = os.getenv("FLASK_ENV","development")
    FLASK_DEBUG = os.getenv("FLASK_DEBUG","1")
    FLASK_APP = os.getenv("FLASK_APP", "oraculoicms_app.wsgi")
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "zfmbet410")
    SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "oraculoicms_session")
    # GOOGLE APIS
    SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "./service_account.json")
    # Database
    # Ex.: postgres://user:pass@localhost:5432/zfm  (Heroku-like)
    # ou:  postgresql+psycopg://user:pass@host:5432/dbname  (SQLAlchemy 2.x)
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/oraculoicms")

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # raiz dos uploads (fora do git, preferível dentro de instance/)
    UPLOAD_FOLDER = os.getenv(
        "UPLOAD_FOLDER",
        os.path.join(BASE_DIR, "uploads")  # absoluto: <raiz do projeto>/uploads
    )

    # Pooling (ajuste conforme host)
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
    }

    # SSL (alguns providers exigem)
    # Para habilitar: export DB_SSLMODE=require
    DB_SSLMODE = os.getenv("DB_SSLMODE")
    if DB_SSLMODE:
        SQLALCHEMY_ENGINE_OPTIONS["connect_args"] = {"sslmode": DB_SSLMODE}
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "http://localhost:5000/billing/sucesso")
    STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "http://localhost:5000/billing/cancelado")

class TestingConfig(Config):
    TESTING = True
    FLASK_ENV = "testing"
    FLASK_DEBUG = "0"
    # Força SQLite em testes, a menos que o ambiente já tenha sido definido
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{os.path.join(BASE_DIR, 'test.sqlite')}"
    )

class StagingConfig(Config):
    FLASK_ENV = "staging"
    FLASK_DEBUG = "0"
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "SQLALCHEMY_DATABASE_URI",
        "postgresql+psycopg://postgres:postgres@db:5432/oraculoicms_staging"
    )

class ProductionConfig(Config):
    FLASK_ENV = "production"
    FLASK_DEBUG = "0"
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "SQLALCHEMY_DATABASE_URI",
        "postgresql+psycopg://postgres:postgres@db:5432/oraculoicms"
    )
