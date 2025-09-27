# zfm_app/blueprints/auth.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from oraculoicms_app import db
from oraculoicms_app.decorators import login_required
from oraculoicms_app.models import User

bp = Blueprint("auth", __name__)

@bp.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        pwd = request.form.get("password")

        u = User.query.filter_by(email=email).first()
        if not u or not u.check_password(pwd):
            flash("Credenciais inválidas.", "danger")
            return redirect(url_for("auth.login"))

        session["user"] = {
            "name": u.name, "email": u.email, "plan": u.plan,
            "is_admin": u.is_admin, "renews_at": "—"
        }
        flash("Login efetuado.", "success")
        next_url = request.args.get("next") or url_for("core.dashboard")
        return redirect(next_url)
    return render_template("auth_login.html")

@bp.route("/logout")
def logout():
    session.clear()
    flash("Você saiu da sessão.", "info")
    return redirect(url_for("core.index"))

@bp.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name","Usuário")
        email = request.form.get("email")
        pwd = request.form.get("password")
        plan = request.form.get("plan","basic")

        if not email or not pwd:
            flash("Informe e-mail e senha.", "warning")
            return redirect(url_for("auth.register"))

        if User.query.filter_by(email=email).first():
            flash("E-mail já cadastrado.", "warning")
            return redirect(url_for("auth.register"))

        u = User(name=name, email=email, plan=plan)
        u.set_password(pwd)
        db.session.add(u)
        db.session.commit()

        session["user"] = {
            "name": u.name, "email": u.email, "plan": u.plan,
            "is_admin": u.is_admin, "renews_at": "—"
        }
        flash("Conta criada com sucesso.", "success")
        return redirect(url_for("core.dashboard"))

    return render_template("auth_register.html")

@bp.route("/account")
@login_required
def account():
    user = session.get("user") or {"name":"Convidado","email":"-","company":"-","plan":"basic","renews_at":"—"}
    return render_template("user_account.html", user=user)

@bp.route("/account/update", methods=["POST"])
@login_required
def account_update():
    u = User.query.filter_by(email=session["user"]["email"]).first()
    if not u:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("auth.account"))

    u.name = request.form.get("name", u.name)
    new_email = request.form.get("email", u.email)
    u.company = request.form.get("company", u.company)

    if new_email != u.email and User.query.filter_by(email=new_email).first():
        flash("E-mail já em uso por outra conta.", "warning")
        return redirect(url_for("auth.account"))
    u.email = new_email

    db.session.commit()
    session["user"].update({"name": u.name, "email": u.email})
    flash("Dados atualizados.", "success")
    return redirect(url_for("auth.account"))

@bp.route("/account/password", methods=["POST"])
@login_required
def password_change():
    u = User.query.filter_by(email=session["user"]["email"]).first()
    if not u:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("auth.account"))
    pwd1 = request.form.get("pwd1")
    pwd2 = request.form.get("pwd2")
    if not pwd1 or pwd1 != pwd2:
        flash("Senhas não conferem.", "warning")
        return redirect(url_for("auth.account"))
    u.set_password(pwd1)
    db.session.commit()
    flash("Senha alterada.", "success")
    return redirect(url_for("auth.account"))
