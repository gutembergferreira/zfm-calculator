# tests/conftest.py
# -*- coding: utf-8 -*-
import os
import sys
import uuid
import pathlib
import importlib
import tempfile
from datetime import datetime

import pytest
from sqlalchemy.orm import DeclarativeMeta
from sqlalchemy import event
from sqlalchemy.engine import Engine

def _set_sqlite_pragmas(dbapi_conn, _conn_record):
    # só funciona em sqlite3
    try:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
    except Exception:
        # silencioso em sqlite corrompido; mas não deve ser chamado em outros backends
        pass


# --------------------------------------------------------------------------------------
# Limpeza de arquivos de DB residuais (ex.: test.sqlite) solicitada pelo usuário
# --------------------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_sqlite_files():
    for fname in ("test.sqlite", "test.db"):
        if os.path.exists(fname):
            try: os.remove(fname)
            except OSError: pass
    yield
    for fname in ("test.sqlite", "test.db"):
        if os.path.exists(fname):
            try: os.remove(fname)
            except OSError: pass

# =====================================================================================
# Localização do projeto (garante que "oraculoicms_app" esteja no sys.path)
# =====================================================================================
def _add_project_root():
    here = pathlib.Path(__file__).resolve()
    for base in [here.parent, here.parent.parent, pathlib.Path.cwd(), pathlib.Path("/app")]:
        for candidate in [base, *base.parents]:
            if (candidate / "oraculoicms_app").is_dir():
                if str(candidate) not in sys.path:
                    sys.path.insert(0, str(candidate))
                return candidate
    env_root = os.getenv("PROJECT_ROOT")
    if env_root and os.path.isdir(env_root):
        if env_root not in sys.path:
            sys.path.insert(0, env_root)
        return pathlib.Path(env_root)
    return None


PROJECT_ROOT = _add_project_root()


# =====================================================================================
# Ambiente de testes unitários (sem serviços externos)
# =====================================================================================
@pytest.fixture(autouse=True, scope="session")
def _testing_env():
    os.environ["APP_ENV"] = "testing"
    os.environ["FLASK_ENV"] = "testing"
    os.environ["TESTING"] = "1"
    os.environ["DISABLE_SHEETS"] = "1"
    os.environ["DISABLE_SCHEDULER"] = "1"
    os.environ.setdefault("SECRET_KEY", "testing-secret")
    yield


def _import(modpath, name=None):
    mod = importlib.import_module(modpath)
    return getattr(mod, name) if name else mod


# =====================================================================================
# App Flask com SQLite temporário e schema criado uma vez por sessão
# - SQLite com timeout e check_same_thread desativado
# - PRAGMAs: WAL + busy_timeout
# =====================================================================================
@pytest.fixture(scope="session")
def app():
    fd, db_path = tempfile.mkstemp(prefix="oraculoicms_test_", suffix=".sqlite")
    os.close(fd)

    # URI com flags para reduzir locks
    os.environ["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}?check_same_thread=0&timeout=30"
    os.environ["DATABASE_URL"] = os.environ["SQLALCHEMY_DATABASE_URI"]

    try:
        wsgi = _import("oraculoicms_app.wsgi", None)
        app = getattr(wsgi, "create_app", None)() if hasattr(wsgi, "create_app") else wsgi.app
    except Exception as e:
        raise RuntimeError(f"Falha ao importar a app Flask: {e} (sys.path={sys.path})")

    from oraculoicms_app.extensions import db
    from sqlalchemy import event

    # PRAGMAs sempre que o engine abrir uma conexão
    def _set_sqlite_pragmas(dbapi_conn, _conn_record):
        try:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
        except Exception:
            pass

    with app.app_context():
        try:
            backend = db.engine.url.get_backend_name()  # 'sqlite', 'postgresql', etc.
            if backend == "sqlite":
                event.listen(db.engine, "connect", _set_sqlite_pragmas)
        except Exception:
            pass

        db.create_all()

        # Aplica também na conexão atual
        try:
            with db.engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA journal_mode=WAL")
                conn.exec_driver_sql("PRAGMA busy_timeout=30000")
        except Exception:
            pass

    yield app

    # teardown
    try:
        from oraculoicms_app.extensions import db
        with app.app_context():
            db.session.remove()
    except Exception:
        pass
    try:
        os.remove(db_path)
    except OSError:
        pass


# =====================================================================================
# Guard: antes de cada teste garanta que NÃO há transações pendentes
# (mitiga locks quando algum teste cria tabelas de modelos próprios)
# =====================================================================================
@pytest.fixture(autouse=True)
def _before_each_test_ddl_guard(app):
    try:
        from oraculoicms_app.extensions import db
        with app.app_context():
            db.session.commit()
    except Exception:
        pass
    yield


# =====================================================================================
# Client e sessão de DB por teste — SEM transação manual
# (evita "database is locked" em DDL do SQLite)
# =====================================================================================
@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    from oraculoicms_app.extensions import db
    with app.app_context():
        try:
            yield db.session
        finally:
            # limpa qualquer pendência sem manter transação aberta
            try:
                db.session.rollback()
            except Exception:
                pass
            try:
                db.session.close()
            except Exception:
                pass


# =====================================================================================
# Mocks de serviços externos
#   - Stripe (Checkout, Portal, Customer)
#   - requests.get/post (sem rede)
# =====================================================================================
@pytest.fixture(autouse=True)
def _mock_externals(monkeypatch):
    # Stripe
    try:
        import stripe

        class _StripeObj:
            def __init__(self, **k):
                self.__dict__.update(k)
            def get(self, k, d=None):
                return getattr(self, k, d)

        monkeypatch.setattr(
            stripe.checkout.Session,
            "create",
            staticmethod(lambda **k: _StripeObj(url="https://stripe.example/checkout/session/test_123")),
            raising=False,
        )
        monkeypatch.setattr(
            stripe.billing_portal.Session,
            "create",
            staticmethod(lambda **k: _StripeObj(url="https://stripe.example/portal/session/test_123")),
            raising=False,
        )
        monkeypatch.setattr(
            stripe.Customer,
            "create",
            staticmethod(lambda **k: _StripeObj(id="cus_test_123", email=k.get("email"), name=k.get("name"))),
            raising=False,
        )
    except Exception:
        pass

    # requests
    try:
        import requests

        class _Resp:
            def __init__(self, status_code=200, json_data=None, text="OK"):
                self.status_code = status_code
                self._json = json_data or {}
                self.text = text
            def json(self):
                return self._json

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(), raising=False)
        monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(), raising=False)
    except Exception:
        pass

    yield


# Compat com @pytest.mark.usefixtures("fake_stripe")
@pytest.fixture(name="fake_stripe")
def _fake_stripe_alias(_mock_externals):
    yield


# =====================================================================================
# Configurações do Stripe no app.config (usadas diretamente pelo billing.py)
# =====================================================================================
@pytest.fixture(autouse=True)
def _billing_ready(app, monkeypatch):
    app.config["STRIPE_SECRET_KEY"] = "sk_test_123"
    app.config["STRIPE_SUCCESS_URL"] = "https://example.test/success"
    app.config["STRIPE_CANCEL_URL"] = "https://example.test/cancel"

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_PUBLIC_KEY", "pk_test_123")
    monkeypatch.setenv("STRIPE_SUCCESS_URL", "https://example.test/success")
    monkeypatch.setenv("STRIPE_CANCEL_URL", "https://example.test/cancel")
    yield


# =====================================================================================
# Helpers/Factories de modelos
# =====================================================================================
def _guess_value_for_column(col):
    tname = col.type.__class__.__name__.lower()
    if "int" in tname:
        return 0
    if "bool" in tname:
        return False
    if "date" in tname or "time" in tname:
        return datetime.utcnow()
    if "float" in tname or "numeric" in tname or "decimal" in tname:
        return 0
    return f"test-{uuid.uuid4().hex[:8]}"


def safe_overrides(Model, **hints):
    """Mantém só chaves presentes no Model.__table__.columns"""
    cols = {c.name for c in Model.__table__.columns}
    return {k: v for k, v in hints.items() if k in cols}


def make_instance(Model, db_session, **overrides):
    """Cria e persiste Model preenchendo NOT NULLs sem default."""
    assert isinstance(Model, DeclarativeMeta), "Model deve ser SQLAlchemy declarative"
    data = dict(overrides)
    for col in Model.__table__.columns:
        name = col.name
        if name in data:
            continue
        if col.primary_key and (getattr(col, "autoincrement", True) or getattr(col, "identity", None)):
            continue
        if getattr(col, "default", None) is not None or getattr(col, "server_default", None) is not None:
            continue
        data[name] = None if col.nullable else _guess_value_for_column(col)
    obj = Model(**data)
    db_session.add(obj)
    db_session.commit()
    return obj


def _has_col(Model, name: str) -> bool:
    return name in {c.name for c in Model.__table__.columns}


def _plan_hints(Model, *, slug, name):
    cols = {c.name for c in Model.__table__.columns}
    hints = {}
    if "slug" in cols: hints["slug"] = slug
    if "name" in cols: hints["name"] = name
    if "active" in cols: hints["active"] = True
    # variações de preço
    if "price_cents" in cols: hints["price_cents"] = 0
    if "price" in cols: hints["price"] = 0
    if "price_month_cents" in cols: hints["price_month_cents"] = 0
    if "price_year_cents" in cols: hints["price_year_cents"] = 0
    # IDs do Stripe que seu billing.py usa
    if "stripe_price_monthly_id" in cols: hints["stripe_price_monthly_id"] = f"price_{slug}_monthly"
    if "stripe_price_yearly_id" in cols: hints["stripe_price_yearly_id"] = f"price_{slug}_yearly"
    return hints


# =====================================================================================
# Usuários e clientes logados
# =====================================================================================
@pytest.fixture
def user_admin(db_session):
    from oraculoicms_app.models.user import User
    email = f"admin+{uuid.uuid4().hex[:6]}@test.com"
    u = User(name="Admin", email=email, company="ORAC", is_admin=True)
    if hasattr(u, "set_password"): u.set_password("secret123")
    db_session.add(u); db_session.commit()
    return u


@pytest.fixture
def user_normal(db_session):
    from oraculoicms_app.models.user import User
    email = f"user+{uuid.uuid4().hex[:6]}@test.com"
    u = User(name="User", email=email, company="ACME")
    if hasattr(u, "set_password"): u.set_password("secret123")
    db_session.add(u); db_session.commit()
    return u


@pytest.fixture
def logged_client_admin(client, user_admin):
    with client.session_transaction() as sess:
        sess["user"] = {"id": user_admin.id, "email": user_admin.email, "is_admin": True}
    return client


@pytest.fixture
def logged_client_user(client, user_normal):
    with client.session_transaction() as sess:
        sess["user"] = {"id": user_normal.id, "email": user_normal.email, "is_admin": False}
    return client


# =====================================================================================
# Planos coerentes com o billing.py
#   - plan_basic: slug "basico", name "Básico"
#   - autouse garante existir "Pro" SEM usar db_session (evita lock em DDL)
# =====================================================================================
# --- SUBSTITUA o fixture plan_basic por este ---

@pytest.fixture
def plan_basic(db_session):
    from sqlalchemy import select
    from oraculoicms_app.models.plan import Plan

    # 1) Tenta reaproveitar se já existir
    existing = db_session.execute(
        select(Plan).where(Plan.slug == "basico")
    ).scalar_one_or_none()
    if existing:
        return existing

    # 2) Monta os hints mínimos para o billing.py funcionar
    hints = _plan_hints(Plan, slug="basico", name="Básico")

    # FK opcional p/ PaymentConfig (se existir no schema)
    try:
        from oraculoicms_app.models.payment_config import PaymentConfig  # noqa
        if _has_col(Plan, "payment_config_id"):
            # pega uma config existente ou cria uma
            cfg_id = db_session.execute(
                db_session.get_bind().exec_driver_sql("SELECT id FROM payment_config LIMIT 1")
            ).scalar()
            if not cfg_id:
                cfg = make_instance(
                    PaymentConfig,
                    db_session,
                    **safe_overrides(PaymentConfig, enabled=True, provider="stripe")
                )
                cfg_id = cfg.id
            hints["payment_config_id"] = cfg_id
    except Exception:
        pass

    # 3) Cria o plano "Básico" e retorna
    return make_instance(Plan, db_session, **safe_overrides(Plan, **hints))



@pytest.fixture(autouse=True)
def _ensure_plan_pro(app):
    """
    Garante que exista um plano 'Pro' ativo para a landing page,
    sem usar db_session (evita transação longa que trava DDL em SQLite).
    """
    from oraculoicms_app.extensions import db
    from oraculoicms_app.models.plan import Plan

    with app.app_context():
        pro = Plan.query.filter_by(slug="pro").first()
        if not pro:
            hints = _plan_hints(Plan, slug="pro", name="Pro")
            try:
                from oraculoicms_app.models.payment_config import PaymentConfig  # noqa
                if _has_col(Plan, "payment_config_id"):
                    cfg = db.session.execute(db.text("SELECT id FROM payment_config LIMIT 1")).scalar()
                    if not cfg:
                        cfg_obj = PaymentConfig()
                        for k, v in {
                            "enabled": True,
                            "provider": "stripe",
                            "public_key": "pk_test_123",
                            "secret_key": "sk_test_123",
                        }.items():
                            if hasattr(cfg_obj, k): setattr(cfg_obj, k, v)
                        db.session.add(cfg_obj); db.session.commit()
                        cfg = cfg_obj.id
                    if "payment_config_id" in {c.name for c in Plan.__table__.columns}:
                        hints["payment_config_id"] = cfg
            except Exception:
                pass
            obj = Plan(**safe_overrides(Plan, **hints))
            db.session.add(obj); db.session.commit()
    yield
