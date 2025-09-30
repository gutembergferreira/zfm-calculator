# tests/test_decorators.py
def test_login_required_redirects(client):
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.location

def test_admin_required_blocks_non_admin(logged_client_user):
    # pega uma rota admin concreta (a listagem de feedback/admin existe no seu projeto)
    resp = logged_client_user.get("/admin/support", follow_redirects=False)
    # sem admin True deve redirecionar pro dashboard
    assert resp.status_code in (302, 308)
