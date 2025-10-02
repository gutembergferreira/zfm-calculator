# tests/test_billing_extra.py
from __future__ import annotations
import time
from datetime import datetime, timezone, timedelta

import pytest


def _mk_plan(db_session, slug="planx", active=True, price_m=None, price_y=None, **extra):
    """Cria um plano isolado para cada teste, evitando conflito de unique slug."""
    from oraculoicms_app.models.plan import Plan
    data = dict(slug=slug, name=slug.capitalize(), active=active,
                stripe_price_monthly_id=price_m, stripe_price_yearly_id=price_y)
    data.update(extra)
    p = Plan(**{k: v for k, v in data.items() if k in {c.name for c in Plan.__table__.columns}})
    db_session.add(p); db_session.commit()
    return p


# --------------------------
# /billing/checkout (falta de price)
# --------------------------
def test_checkout_missing_price_redirects(client, db_session, logged_client_user):
    # Plano sem price_id -> checkout/<slug>/<cycle> deve redirecionar de volta para /billing/checkout
    p = _mk_plan(db_session, slug="noprice", price_m=None, price_y=None)

    r = client.get(f"/billing/checkout/{p.slug}/monthly", follow_redirects=False)
    # redireciona para a tela de escolha (/billing/checkout)
    assert r.status_code in (302, 303)
    assert (r.headers.get("Location") or "").endswith("/billing/checkout")


# --------------------------
# /billing/portal (sem customer_id)
# --------------------------
def test_portal_without_customer_redirects(client, db_session, logged_client_user, user_normal):
    # Cria sub placeholder sem provider_cust_id
    from oraculoicms_app.models.plan import Plan
    from oraculoicms_app.models.user import User
    from oraculoicms_app.models.plan import Subscription

    plan = _mk_plan(db_session, slug="porta", price_m="price_porta_m")
    sub = Subscription(user_id=user_normal.id, plan_id=plan.id, provider="stripe", provider_cust_id=None)
    db_session.add(sub); db_session.commit()

    r = client.get("/billing/portal", follow_redirects=False)
    assert r.status_code in (302, 303)
    # volta para escolha de plano
    assert (r.headers.get("Location") or "").endswith("/billing/checkout")


# --------------------------
# /billing/webhook (assinatura inválida)
# --------------------------
def test_webhook_bad_signature_returns_400(client, monkeypatch):
    # Força o construct_event a lançar exceção
    import stripe
    def boom(payload, sig, secret):
        raise Exception("bad sig")
    monkeypatch.setattr(stripe.Webhook, "construct_event", staticmethod(boom), raising=True)

    r = client.post("/billing/webhook", data=b"{}", headers={"Stripe-Signature": "t=1,v1=deadbeef"})
    assert r.status_code == 400


# --------------------------
# /billing/webhook (subscription updated -> cria/atualiza sub, vincula plano)
# --------------------------
def test_webhook_subscription_update_creates_and_links_everything(client, db_session, monkeypatch):
    """
    Simula um evento 'customer.subscription.updated':
    - Recupera a subscription no Stripe com price.id correspondente a um Plan local
    - Recupera Customer por id e encontra User por e-mail
    - Atualiza/cria Subscription local e sincroniza user.plan
    """
    # Arrange: cria User e Plan compatíveis
    from oraculoicms_app.models.user import User
    from oraculoicms_app.models.plan import Plan, Subscription

    email = "wbk-user@test.com"
    user = User(name="Wbk User", email=email, company="ACME")
    user.set_password("x")
    db_session.add(user); db_session.commit()

    price_id = "price_wbk_m"
    plan = _mk_plan(db_session, slug="wbk", price_m=price_id, price_y=None, active=True)

    # Mock Stripe SDK usado pelo blueprint
    import stripe

    now = int(time.time())
    fake_sub = {
        "id": "sub_123",
        "status": "active",
        "current_period_start": now,
        "current_period_end": now + 30 * 24 * 3600,
        "items": {
            "data": [
                {"price": {"id": price_id, "unit_amount": 12900, "recurring": {"interval": "month"}}}
            ]
        }
    }

    def sub_retrieve(sub_id):
        assert sub_id == "sub_123"
        return fake_sub

    def cust_retrieve(cust_id):
        # retorna o e-mail do usuário para vincular
        return {"id": cust_id, "email": email}

    def ok_construct(payload, sig, secret):
        # evento de atualização de assinatura
        return {
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_123", "customer": "cus_999"}}
        }

    monkeypatch.setattr(stripe.Subscription, "retrieve", staticmethod(sub_retrieve), raising=True)
    monkeypatch.setattr(stripe.Customer, "retrieve", staticmethod(cust_retrieve), raising=True)
    monkeypatch.setattr(stripe.Webhook, "construct_event", staticmethod(ok_construct), raising=True)

    # Também precisamos impedir que o blueprint tente acessar uma SECRET real
    # (suas fixtures já setam STRIPE_* no app, mas garantimos aqui).
    r = client.post("/billing/webhook", data=b"{}", headers={"Stripe-Signature": "t=1,v1=ok"})
    assert r.status_code == 200
    assert r.is_json and r.get_json().get("received") is True

    # Assert: Subscription criada/atualizada e vinculada
    sub = db_session.query(Subscription).filter_by(provider_cust_id="cus_999").first()
    assert sub is not None
    assert sub.user_id == user.id
    assert sub.plan_id == plan.id
    assert sub.provider_sub_id == "sub_123"
    assert sub.status == "active"
    # ciclo e valor
    assert sub.billing_cycle in ("month", "monthly")  # blueprint seta 'month'
    assert isinstance(sub.amount_cents, int) and sub.amount_cents == 12900
    # user.plan sincronizado com slug do plano
    db_session.refresh(user)
    assert user.plan == plan.slug
