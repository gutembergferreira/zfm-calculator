def test_admin_required_blocks(logged_client_user):
    r = logged_client_user.get("/admin", follow_redirects=False)
    assert r.status_code in (302, 303,404 )
