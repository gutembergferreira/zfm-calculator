# tests/conftest.py
import os
import sys
import uuid
import tempfile
import importlib
import types
import pytest
import stripe

# Garante que a raiz do projeto está no sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---- Stub do Google Sheets para testes ----
def fake_init_sheets(app):
    # o código de produção acessa estas chaves:
    app.extensions["sheet_client"] = types.SimpleNamespace(
        service_email="test-service@fake",
        title="Planilha de Teste",
        worksheets=[]
    )
    app.extensions["matrices"] = {
        "version": "test",
        "rules": [],
        "sources": [],
    }
    app.extensions["worksheets"] = []

def _import(path, name=None):
    return __import__(path, fromlist=["*"])


# ---- Fixture principal da app (um SQLite ARQUIVO novo por teste) ----
@pytest.fixture(scope="function")
def app():
    # SQLite exclusivo por teste
    db_path = os.path.join(tempfile.gettempdir(), f"oraculo_test_{uuid.uuid4().hex}.sqlite3")
    test_db_uri = f"sqlite:///{db_path}"

    # Força variáveis ANTES de importar a app
    os.environ["DATABASE_URL"] = test_db_uri
    os.environ["SQLALCHEMY_DATABASE_URI"] = test_db_uri
    os.environ["DISABLE_SEED"] = "1"
    os.environ["SKIP_SHEETS"] = "1"
    os.environ["DISABLE_SCHEDULER"] = "1"
    os.environ["FLASK_ENV"] = "testing"
    os.environ["TESTING"] = "1"
    # se houver alguma flag de pular stripe no seu código, limpe:
    os.environ.pop("SKIP_STRIPE", None)

    # importa wsgi depois do env estar pronto
    wsgi = _import("oraculoicms_app.wsgi", "wsgi")
    app = getattr(wsgi, "create_app", None)() if hasattr(wsgi, "create_app") else wsgi.app

    # cria/destroi schema neste arquivo
    from oraculoicms_app.extensions import db
    with app.app_context():
        #db.drop_all()
        db.create_all()

    yield app

    # teardown: fecha sessão e apaga o arquivo
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


# ---- Client HTTP ----
@pytest.fixture(scope="function")
def client(app):
    return app.test_client()

@pytest.fixture(scope="function")
def db_session(app):
    from oraculoicms_app.extensions import db
    with app.app_context():
        yield db.session
        db.session.rollback()

# ---- Acesso prático aos modelos ----
def _models():
    m_user = importlib.import_module("oraculoicms_app.models.user")
    m_plan = importlib.import_module("oraculoicms_app.models.plan")
    m_payment = importlib.import_module("oraculoicms_app.models.payment")
    return m_user, m_plan, m_payment

# ---- Fixtures de dados (sem colisão de unique) ----
import uuid

@pytest.fixture
def plan_basic(db_session):
    from oraculoicms_app.models.plan import Plan
    slug = f"basic_{uuid.uuid4().hex[:6]}"
    p = Plan(
        slug=slug,
        name="Básico",
        price_month_cents=4900,
        price_year_cents=49000,
        currency="BRL",
        trial_days=7,
        max_uploads_month=300,
        max_storage_mb=512,
        active=True,
        stripe_price_monthly_id="price_monthly_test",
        stripe_price_yearly_id="price_yearly_test",
    )
    db_session.add(p)
    db_session.commit()
    return p

@pytest.fixture
def user_admin(db_session):
    m_user, _, _ = _models()
    User = getattr(m_user, "User")
    email = f"admin+{uuid.uuid4().hex[:6]}@test.com"
    u = User(name="Admin", email=email, company="ZFM", is_admin=True)
    u.set_password("secret123")
    db_session.add(u); db_session.commit()
    return u

@pytest.fixture
def user_normal(db_session):
    from oraculoicms_app.models.user import User
    u = User(name="User", email=f"user_{uuid.uuid4().hex[:6]}@test.com", company="ACME")
    u.set_password("secret123")
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

# ---- Stripe fake por teste ----
@pytest.fixture
def fake_stripe(monkeypatch):
    class _FakeSessionObj:
        def __init__(self, url):
            self.url = url

    # Finge a criação de sessão de Checkout
    def _fake_checkout_create(**kwargs):
        return _FakeSessionObj("https://stripe.com/checkout/session/test_123")

    # Finge a criação de sessão do Billing Portal
    def _fake_portal_create(**kwargs):
        return _FakeSessionObj("https://billing.stripe.com/session/test_123")

    # Importante: patchar exatamente os objetos que seu código usa
    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(_fake_checkout_create))
    monkeypatch.setattr(stripe.billing_portal.Session, "create", staticmethod(_fake_portal_create))

    yield

