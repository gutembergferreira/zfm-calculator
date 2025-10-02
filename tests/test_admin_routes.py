# tests/test_admin_routes.py
# -*- coding: utf-8 -*-
import types
import pytest
from decimal import Decimal

# módulo sob teste
import oraculoicms_app.blueprints.admin.routes as admin_routes

from oraculoicms_app.extensions import db
from oraculoicms_app.models import User, Plan, Payment, Subscription


# -----------------------------------------------------------------------------
# Helpers puros
# -----------------------------------------------------------------------------
def test__to_cents_variants():
    f = admin_routes._to_cents
    assert f(None) == 0
    assert f("") == 0
    assert f("0") == 0
    assert f("10") == 1000
    assert f("10,50") == 1050
    assert f("10.50") == 105000
    assert f("  1.234,56  ") == 123456  # milhar com ponto + vírgula decimal


def test__first_helper():
    assert admin_routes._first([1, 2, 3]) == 1
    assert admin_routes._first([]) is None
    assert admin_routes._first(None) is None


# -----------------------------------------------------------------------------
# Fixtures auxiliares destes testes
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _mock_render(monkeypatch):
    # evita depender de templates reais
    monkeypatch.setattr(admin_routes, "render_template", lambda *a, **k: "OK", raising=True)
    yield


@pytest.fixture(autouse=True)
def _mock_balance_in_system_snapshot(monkeypatch):
    # _system_snapshot chama stripe.Balance.retrieve() — deixe inofensivo
    class _Obj: ...
    monkeypatch.setattr(admin_routes.stripe.Balance, "retrieve", staticmethod(lambda: _Obj()), raising=False)
    yield


# -----------------------------------------------------------------------------
# Painel e .env
# -----------------------------------------------------------------------------
def test_admin_panel_renders(client, logged_client_admin, monkeypatch):
    # dotenv_values chamado por admin(); devolve dict fake
    monkeypatch.setattr(admin_routes, "dotenv_values", lambda p: {"FOO": "BAR"}, raising=True)
    r = client.get("/admin/admin")
    assert r.status_code == 200
    assert r.get_data(as_text=True) == "OK"


def test_admin_env_update_writes(client, logged_client_admin, monkeypatch):
    calls = []

    def fake_set_key(path, k, v):
        calls.append((str(path), k, v))
        return (k, v, True)

    monkeypatch.setattr(admin_routes, "set_key", fake_set_key, raising=True)
    monkeypatch.setattr(admin_routes, "dotenv_values", lambda p: {}, raising=True)

    r = client.post(
        "/admin/admin/env",
        data={"key": ["A", "B", ""], "value": ["1", "2", ""]},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    keys = [k for (_, k, _) in calls]
    assert "A" in keys and "B" in keys


# -----------------------------------------------------------------------------
# Usuários
# -----------------------------------------------------------------------------
def test_admin_users_create_validation(client, logged_client_admin):
    # falta de campos obrigatórios -> redirect com flash (não 404)
    r = client.post("/admin/admin/users/create", data={"name": "", "email": ""})
    assert r.status_code in (302, 303)


def test_admin_users_create_and_update(client, logged_client_admin, db_session):
    # Create
    email = "novo@teste.com"
    r = client.post(
        "/admin/admin/users/create",
        data={"name": "Novo", "email": email, "company": "ACME", "plan": "basic", "password": "123"},
    )
    assert r.status_code in (302, 303)
    u = User.query.filter_by(email=email).first()
    assert u.company == "ACME" and u.plan == "basic"

    # Update
    r2 = client.post(
        f"/admin/admin/users/{u.id}/update",
        data={"name": "Novo Nome", "email": email, "company": "ACME2", "plan": "pro", "active": "on", "is_admin": "on"},
    )
    assert r2.status_code in (302, 303)
    db.session.refresh(u)
    assert u.name == "Novo Nome"
    assert u.company == "ACME2"
    assert u.plan == "pro"
    assert bool(getattr(u, "active", True)) is True
    assert bool(getattr(u, "is_admin", True)) is True


# -----------------------------------------------------------------------------
# Planos
# -----------------------------------------------------------------------------
def test_admin_plans_create_and_update(client, logged_client_admin, db_session):
    # Create
    r = client.post(
        "/admin/admin/plans/create",
        data={
            "slug": "gold",
            "name": "Gold",
            "description_md": "desc",
            "active": "on",
            "price_month": "10,00",
            "price_year": "100,00",
            "stripe_price_monthly_id": "price_m",
            "stripe_price_yearly_id": "price_y",
            "trial_days": "14",
            "trial_xml_quota": "5",
            "max_files": "10",
            "max_storage_mb": "500",
            "max_uploads_month": "100",
        },
    )
    assert r.status_code in (302, 303)
    p = Plan.query.filter_by(slug="gold").first()
    assert p is not None
    assert p.price_month_cents == 1000 and p.price_year_cents == 10000
    assert p.trial_days == 14 and p.trial_xml_quota == 5
    assert p.max_files == 10 and p.max_storage_mb == 500 and p.max_uploads_month == 100

    # Update
    r2 = client.post(
        f"/admin/admin/plans/{p.id}/update",
        data={"slug": "gold", "name": "Gold+", "active": "on", "price_month": "12,34", "price_year": "111,11"},
    )
    assert r2.status_code in (302, 303)
    db.session.refresh(p)
    assert p.name == "Gold+"
    assert p.price_month_cents == 1234 and p.price_year_cents == 11111


# -----------------------------------------------------------------------------
# Listagem de faturas (Stripe)
# -----------------------------------------------------------------------------
def test_admin_payments_list_filters(client, logged_client_admin, monkeypatch):
    # Mocks Stripe Customer.search / list e Invoice.list
    class _ListObj:
        def __init__(self, data=None, has_more=False):
            self.data = data or []
            self.has_more = has_more

        # compat com auto_paging_iter usado no fallback
        def auto_paging_iter(self):
            for x in self.data:
                yield x

    class _Cust:
        def __init__(self, id, email):
            self.id = id
            self.email = email

    class _InvLinePrice:
        def __init__(self, id):
            self.id = id
            self.product = {"name": "Plan X"}
            self.nickname = None

    class _InvLine:
        def __init__(self, price):
            self.price = price

    class _Inv:
        def __init__(self, id_):
            self.id = id_
            self.customer = None
            self.subscription = None
            self.payment_intent = None
            self.lines = types.SimpleNamespace(data=[_InvLine(_InvLinePrice("price_test"))])

    # Customer.search encontra 1
    monkeypatch.setattr(
        admin_routes.stripe.Customer,
        "search",
        staticmethod(lambda query, limit=1: _ListObj([_Cust("cus_1", "search@x.com")])),
        raising=False,
    )
    # Fallback (não usado aqui, mas seguro)
    monkeypatch.setattr(
        admin_routes.stripe.Customer,
        "list",
        staticmethod(lambda limit=100: _ListObj([])),
        raising=False,
    )
    # Invoice.list volta 1 invoice
    monkeypatch.setattr(
        admin_routes.stripe.Invoice,
        "list",
        staticmethod(lambda **params: _ListObj([_Inv("in_1")], has_more=False)),
        raising=False,
    )

    r = client.get("/admin/admin/payments?email=search@x.com&status=paid")
    assert r.status_code == 200
    assert r.get_data(as_text=True) == "OK"


# -----------------------------------------------------------------------------
# Validar fatura -> cria/atualiza Payment e Subscription locais
# -----------------------------------------------------------------------------
def test_admin_payment_validate_creates_records(client, logged_client_admin, db_session, monkeypatch):
    # Usuário com e-mail
    email = "buyer@x.com"
    u = User(name="Buyer", email=email, company="C")
    u.set_password("x"); db.session.add(u); db.session.commit()

    # Plano com price id do Stripe usado na invoice fake
    p = Plan(slug="plus", name="Plus", active=True, stripe_price_monthly_id="price_plus_m")
    db.session.add(p); db.session.commit()

    # Stripe Invoice.retrieve mock
    class _Price:
        def __init__(self, id):
            self.id = id
            self.product = {"name": "Plus"}
            self.nickname = None

    class _Line:
        def __init__(self, price):
            self.price = price

    class _Cust:
        def __init__(self, id, email):
            self.id = id
            self.email = email

    class _Inv:
        def __init__(self):
            self.id = "in_test"
            self.status = "paid"
            self.amount_paid = 1234  # cents
            self.number = "0001"
            self.customer = _Cust("cus_999", email)  # objeto já expandido
            self.subscription = None
            self.payment_intent = None
            self.lines = types.SimpleNamespace(data=[_Line(_Price("price_plus_m"))])
            self.charge = None

    monkeypatch.setattr(admin_routes.stripe.Invoice, "retrieve", staticmethod(lambda *a, **k: _Inv()), raising=False)
    monkeypatch.setattr(
        admin_routes.stripe.Customer, "retrieve", staticmethod(lambda id_: _Cust(id_, email)), raising=False
    )
    monkeypatch.setattr(
        admin_routes.stripe.Subscription, "retrieve", staticmethod(lambda id_: types.SimpleNamespace(id=id_)), raising=False
    )

    r = client.post("/admin/admin/payments/in_test/validate", data={})
    assert r.status_code in (302, 303)

    pay = Payment.query.filter_by(external_id="in_test", provider="stripe").first()
    assert pay is not None
    assert pay.amount == Decimal("12.34")
    db.session.refresh(u)
    assert u.plan == "plus"

    sub = Subscription.query.filter_by(provider_cust_id="cus_999").first()
    assert sub is not None
    assert sub.plan_id == p.id
    assert sub.status in ("paid", "active", "unpaid", "past_due")  # depende do status mapeado


# -----------------------------------------------------------------------------
# Refund
# -----------------------------------------------------------------------------
def test_admin_payment_refund_ok(client, logged_client_admin, monkeypatch):
    class _Inv:
        def __init__(self):
            self.id = "in_x"
            self.payment_intent = types.SimpleNamespace(latest_charge="ch_123")
            self.charge = None

    called = {"ok": False}

    monkeypatch.setattr(admin_routes.stripe.Invoice, "retrieve", staticmethod(lambda *a, **k: _Inv()), raising=False)
    monkeypatch.setattr(
        admin_routes.stripe.Refund, "create", staticmethod(lambda **k: called.update(ok=True)), raising=False
    )

    r = client.post("/admin/admin/payments/in_x/refund", data={})
    assert r.status_code in (302, 303)
    assert called["ok"] is True


def test_admin_payment_refund_without_charge(client, logged_client_admin, monkeypatch):
    class _Inv:
        def __init__(self):
            self.id = "in_nocharge"
            self.payment_intent = types.SimpleNamespace(latest_charge=None)
            self.charge = None

    monkeypatch.setattr(admin_routes.stripe.Invoice, "retrieve", staticmethod(lambda *a, **k: _Inv()), raising=False)

    r = client.post("/admin/admin/payments/in_nocharge/refund", data={})
    # Sem charge -> apenas redirect com flash
    assert r.status_code in (302, 303)

