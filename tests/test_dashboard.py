def test_dashboard_user(logged_client_user):
    r = logged_client_user.get("/dashboard")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Minha conta" or "Assinatura" or "Seu plano"  # qualquer um dos labels

def test_dashboard_admin(logged_client_admin):
    r = logged_client_admin.get("/dashboard")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "MRR" in html or "Assinaturas" in html
