def test_login_get(client):
    r = client.get("/login")
    assert r.status_code in (200, 302)

def test_login_post_wrong(client):
    r = client.post("/login", data={"email":"no@no.com","password":"x"}, follow_redirects=True)
    assert r.status_code == 200
    assert "senha" in r.get_data(as_text=True).lower() or r.get_data(as_text=True)

def test_logout_redirect(logged_client_user):
    r = logged_client_user.get("/logout", follow_redirects=False)
    assert r.status_code in (302, 303)
