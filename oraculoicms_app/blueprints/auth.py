# zfm_app/blueprints/auth.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from oraculoicms_app import db
from oraculoicms_app.blueprints.files import current_user
from oraculoicms_app.decorators import login_required
from oraculoicms_app.models import User, Subscription, Plan

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

def _human_bytes(b):
    b = int(b or 0)
    mb = b / (1024*1024)
    if mb < 1024: return f"{mb:.1f} MB"
    gb = mb/1024; return f"{gb:.2f} GB"

def _user_storage_bytes(user_id):
    total = 0
    # total = db.session.query(func.coalesce(func.sum(Upload.size_bytes), 0)).filter(Upload.user_id==user_id).scalar() or 0
    return int(total)

@bp.route("/account")
@login_required
def account():
    u = current_user()

    # assinatura + plano
    sub = (Subscription.query
           .filter_by(user_id=u.id)
           .order_by(Subscription.created_at.desc())
           .first())
    plan = None
    if sub and sub.plan_id:
        plan = Plan.query.get(sub.plan_id)
    if not plan and u.plan:  # fallback por slug
        plan = Plan.query.filter_by(slug=u.plan).first()

    price_m = float((plan.price_month_cents or 0)/100.0) if plan else None
    price_y = float((plan.price_year_cents or 0)/100.0) if plan else None

    # quotas
    nfe_quota = plan.max_uploads_month if plan else None
    # usados no mês:
    nfe_used_month = 0
    # nfe_used_month = db.session.query(func.count(NFe.id)).filter(NFe.user_id==u.id, func.date_trunc('month', NFe.created_at)==func.date_trunc('month', func.now())).scalar() or 0
    nfe_left = (nfe_quota - nfe_used_month) if nfe_quota is not None else None

    # storage
    used_bytes = _user_storage_bytes(u.id)
    cap_mb = plan.max_storage_mb if plan else None
    cap_bytes = cap_mb * 1024 * 1024 if cap_mb else None
    storage_pct = int((used_bytes*100 // cap_bytes)) if cap_bytes else 0

    acct = dict(
        plan_name=plan.name if plan else None,
        cycle=sub.cycle if sub and getattr(sub, "cycle", None) else None,   # 'monthly'|'yearly' se você guardar
        sub_status=sub.status if sub else None,
        sub_id=sub.provider_sub_id if sub else None,
        next_renewal=sub.period_end.strftime("%d/%m/%Y") if (sub and sub.period_end) else None,
        trial_days_left=max((plan.trial_days or 0) - (datetime.utcnow().date() - u.created_at.date()).days, 0) if (plan and plan.trial_days and u.created_at) else None,
        price_m=price_m if price_m else None,
        price_y=price_y if price_y else None,


        nfe_quota=nfe_quota,
        nfe_used_month=nfe_used_month,
        nfe_left=nfe_left,

        storage_used_human=_human_bytes(used_bytes),
        storage_cap_human=(f"{cap_mb} MB" if cap_mb else None),
        storage_pct=storage_pct,

        # se você gerar um link do portal da Stripe server-side, injete aqui:
        portal_url=None,
    )

    return render_template("user_account.html", user=u, acct=acct)


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

