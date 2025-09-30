import pytest

@pytest.mark.usefixtures("fake_stripe")
def test_checkout_monthly_flow(logged_client_user, plan_basic):
    r = logged_client_user.post(
        "/billing/checkout",
        data={"plan_id": plan_basic.id, "cycle": "monthly"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)

    loc1 = (r.location or "")
    if "stripe" in loc1.lower():
        # fluxo 1-passo
        return

    # fluxo 2-passos
    assert loc1.startswith("/billing/checkout/")
    r2 = logged_client_user.get(loc1, follow_redirects=False)
    assert r2.status_code in (302, 303)
    assert "stripe" in (r2.location or "").lower()

@pytest.mark.usefixtures("fake_stripe")
def test_checkout_yearly_flow(logged_client_user, db_session, plan_basic):
    # garanta que o plano tem price_year_cents
    r = logged_client_user.post("/billing/checkout", data={"plan_id": plan_basic.id, "cycle":"yearly"}, follow_redirects=False)
    assert r.status_code in (302, 303)
