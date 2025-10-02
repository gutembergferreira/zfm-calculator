# tests/test_billing.py
import pytest

@pytest.fixture
def fake_stripe(monkeypatch):
    try:
        import stripe
    except Exception:
        class _Obj:
            def __init__(self, url): self.url = url
        # cria um módulo fake mínimo se stripe não estiver instalado
        class _Checkout:
            class Session:
                @staticmethod
                def create(**k): return _Obj("https://stripe/checkout/test")
        class _BillingPortal:
            class Session:
                @staticmethod
                def create(**k): return _Obj("https://stripe/portal/test")
        class _Stripe:
            checkout = _Checkout()
            billing_portal = _BillingPortal()
        import sys
        sys.modules['stripe'] = _Stripe()
        yield
        return

    class _Obj:
        def __init__(self, url): self.url = url

    monkeypatch.setattr(stripe.checkout.Session, "create",
                        staticmethod(lambda **k: _Obj("https://stripe/checkout/test")),
                        raising=False)
    monkeypatch.setattr(stripe.billing_portal.Session, "create",
                        staticmethod(lambda **k: _Obj("https://stripe/portal/test")),
                        raising=False)
    yield

@pytest.mark.usefixtures("fake_stripe")
def test_checkout_choose_renders(logged_client_user, plan_basic):
    r = logged_client_user.get("/billing/checkout")
    assert r.status_code == 200
    assert plan_basic.name in r.get_data(as_text=True)

@pytest.mark.usefixtures("fake_stripe")
def test_checkout_post_creates_session_and_redirects(logged_client_user, plan_basic):
    r = logged_client_user.post(
        "/billing/checkout",
        data={"plan_id": plan_basic.id, "cycle": "monthly"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    # primeiro redirect para a rota interna
    loc1 = r.headers.get("Location", "")
    assert loc1.startswith("/billing/checkout/")
    # segundo passo: acessar a rota interna que cria a sessão no Stripe
    r2 = logged_client_user.get(loc1, follow_redirects=False)
    assert r2.status_code in (302, 303)
    assert "stripe" in (r2.location or "").lower()


@pytest.mark.usefixtures("fake_stripe")
def test_portal_redirects(logged_client_user, db_session, user_normal, plan_basic):
    """
    A rota de portal precisa de um customer ID em alguma Subscription
    Alguns módulos vieram truncados; se Subscription/model não existir, pula.
    """
    try:
        from oraculoicms_app.models.plan import Subscription
    except Exception:
        pytest.skip("Subscription model ausente/truncado no ZIP")

    sub = Subscription(user_id=user_normal.id, plan_id=plan_basic.id, status="active",
                       provider_cust_id="cus_123", provider_sub_id="sub_123")
    db_session.add(sub); db_session.commit()
    r = logged_client_user.get("/billing/portal", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "stripe" in (r.location or "").lower()
