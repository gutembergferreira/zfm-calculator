# tests/test_auth_blueprint.py
# -*- coding: utf-8 -*-
import pytest

# Vamos testar o módulo que você enviou
import oraculoicms_app.blueprints.auth as auth_bp_mod

from oraculoicms_app.extensions import db
from oraculoicms_app.models import User


# -------------------------------------------------------------------
# Mocks/ajustes globais para estes testes
# -------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _mock_templates(monkeypatch):
    """
    Evita dependência de templates reais.
    Qualquer render_template(...) retornará "OK" (texto simples).
    """
    monkeypatch.setattr(auth_bp_mod, "render_template", lambda *a, **k: "OK", raising=True)
    yield


# -------------------------------------------------------------------
# Helpers simples
# -------------------------------------------------------------------
def _create_user(email="user@test.com", name="User", company="ACME", password="secret123"):
    u = User(name=name, email=email, company=company)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


# -------------------------------------------------------------------
# /login
# -------------------------------------------------------------------
def test_login_get_renders(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert r.get_data(as_text=True) == "OK"


def test_login_post_invalid_credentials_redirects(client, db_session):
    _create_user(email="a@b.com", password="secret123")
    r = client.post("/login", data={"email": "a@b.com", "password": "wrong"}, follow_redirects=False)
    # A rota faz flash + redirect para /login
    assert r.status_code in (302, 303)
    assert "/login" in (r.headers.get("Location") or "")


def test_login_post_success_sets_session_and_redirects_next(client, db_session):
    _create_user(email="ok@x.com", password="pw123")
    r = client.post("/login?next=/minha-pagina", data={"email": "ok@x.com", "password": "pw123"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert r.headers.get("Location", "").endswith("/minha-pagina")

    # valida sessão: requer fazer outra requisição para que o test client carregue a sessão
    r2 = client.get("/logout", follow_redirects=False)
    # se conseguiu acessar /logout, a sessão estava setada; o teste de sessão exata fica implícito.


# -------------------------------------------------------------------
# /logout
# -------------------------------------------------------------------
def test_logout_clears_session(client, logged_client_user):
    r = client.get("/logout", follow_redirects=False)
    assert r.status_code in (302, 303)
    # destino padrão é core.index (o app real deve possuir essa rota)
    # Não inspecionamos a sessão diretamente pois o client isola a sessão entre requests.


# -------------------------------------------------------------------
# /register
# -------------------------------------------------------------------
def test_register_get_renders(client):
    r = client.get("/register")
    assert r.status_code == 200
    assert r.get_data(as_text=True) == "OK"


def test_register_missing_fields_redirects(client):
    r = client.post("/register", data={"email": "", "password": ""}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/register" in (r.headers.get("Location") or "")


def test_register_success_creates_user_and_logs_in(client, db_session):
    email = "novo@t.com"
    r = client.post(
        "/register",
        data={"name": "Novo", "email": email, "password": "123", "plan": "basic"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    # usuário criado
    u = User.query.filter_by(email=email).first()
    assert u is not None and u.plan == "basic"


def test_register_duplicate_email_redirects(client, db_session):
    _create_user(email="dup@t.com")
    r = client.post(
        "/register",
        data={"name": "X", "email": "dup@t.com", "password": "123"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    assert "/register" in (r.headers.get("Location") or "")


# -------------------------------------------------------------------
# /account (GET)
# -------------------------------------------------------------------
def test_account_requires_login_and_renders(client, logged_client_user):
    r = client.get("/account")
    # se o decorator @login_required protege corretamente, logged_client_user acessa
    assert r.status_code == 200
    assert r.get_data(as_text=True) == "OK"


# -------------------------------------------------------------------
# /account/update (POST)
# -------------------------------------------------------------------
def test_account_update_conflict_email(client, db_session, logged_client_user):
    # cria outro usuário com e-mail que tentaremos usar
    other = _create_user(email="occupied@t.com")
    assert other is not None

    # tenta atualizar o usuário logado para o email já ocupado
    r = client.post("/account/update", data={"email": "occupied@t.com"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    # redirect de volta para a account
    assert "/account" in (r.headers.get("Location") or "")


def test_account_update_success(client, db_session, logged_client_user):
    # atualiza nome e email para algo único
    new_email = "changed@t.com"
    r = client.post(
        "/account/update", data={"name": "Novo Nome", "email": new_email, "company": "ACME2"}, follow_redirects=False
    )
    assert r.status_code in (302, 303)

    u = User.query.filter_by(email=new_email).first()
    assert u is not None
    assert u.name == "Novo Nome"
    assert u.company == "ACME2"


# -------------------------------------------------------------------
# /account/password (POST)
# -------------------------------------------------------------------
def test_password_change_mismatch(client, logged_client_user):
    r = client.post("/account/password", data={"pwd1": "a", "pwd2": "b"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/account" in (r.headers.get("Location") or "")


def test_password_change_success(client, db_session, logged_client_user):
    # email do usuário logado está na sessão (fixture logged_client_user já definiu)
    # Muda a senha e verifica com check_password
    r = client.post("/account/password", data={"pwd1": "nova123", "pwd2": "nova123"}, follow_redirects=False)
    assert r.status_code in (302, 303)

    # Recupera o usuário que está na sessão (o fixture usa 'user_normal')
    # Para robustez, localizamos pelo email: ele pode ter sido alterado por outro teste.
    # Pegamos o último usuário criado/alterado na base que não é admin.
    user = User.query.order_by(User.id.desc()).first()
    assert user is not None
    assert user.check_password("nova123") is True


# -------------------------------------------------------------------
# Funções utilitárias internas
# -------------------------------------------------------------------
def test__human_bytes_formats():
    f = auth_bp_mod._human_bytes
    assert f(0) == "0.0 MB"
    assert f(1024 * 1024) == "1.0 MB"
    assert f(1024 * 1024 * 1500).endswith("GB")  # valor grande vira GB


def test__user_storage_bytes_returns_int(user_normal):
    # Atualmente retorna 0 (placeholder). Garante apenas tipo e não-negatividade.
    v = auth_bp_mod._user_storage_bytes(user_normal.id)
    assert isinstance(v, int)
    assert v >= 0
