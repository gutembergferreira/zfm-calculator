# app/blueprints/admin/routes.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from decimal import Decimal
from flask import render_template, request, redirect, url_for, flash, session
from ..admin import admin_bp
from ...decorators import admin_required
from ...extensions import db
from ...models import User, Plan, Payment
from ...services.settings import get_setting, set_setting


# ---------------- ADMIN: Painel ----------------
@admin_bp.route("/admin")
@admin_required
def admin():
    users = User.query.order_by(User.created_at.desc()).all()
    plans = Plan.query.order_by(Plan.price.asc()).all()

    services = [
        {"name": "Atualizador AM", "ok": True},
        {"name": "Sheets API", "ok": True},
        {"name": "PDF Service", "ok": True},
    ]

    latest_payments = Payment.query.order_by(Payment.created_at.desc()).limit(10).all()

    cfg = {
        "pix_key": get_setting("pix_key", "payments", ""),
        "pix_receiver": get_setting("pix_receiver", "payments", ""),
        "webhook_url": get_setting("webhook_url", "webhooks", ""),
        "webhook_secret": get_setting("webhook_secret", "webhooks", ""),
    }

    return render_template(
        "admin_panel.html",
        users=users, plans=plans, services=services, payments=latest_payments, cfg=cfg
    )

# ---------------- ADMIN: Usuários ----------------
@admin_bp.route("/admin/users/create", methods=["POST"])
@admin_required
def admin_users_create():
    name = request.form.get("name")
    email = request.form.get("email")
    company = request.form.get("company")
    plan = request.form.get("plan", "basic")
    pwd = request.form.get("password", "123456")

    if not name or not email:
        flash("Nome e e-mail são obrigatórios.", "warning")
        return redirect(url_for("admin_bp.admin"))

    if User.query.filter_by(email=email).first():
        flash("E-mail já cadastrado.", "warning")
        return redirect(url_for("admin_bp.admin"))

    u = User(name=name, email=email, company=company, plan=plan)
    u.set_password(pwd)
    db.session.add(u); db.session.commit()
    flash("Usuário criado.", "success")
    return redirect(url_for("admin_bp.admin"))

@admin_bp.route("/admin/users/<int:user_id>/update", methods=["POST"])
@admin_required
def admin_users_update(user_id):
    u = User.query.get_or_404(user_id)
    u.name = request.form.get("name", u.name)
    new_email = request.form.get("email", u.email)
    u.company = request.form.get("company", u.company)
    u.plan = request.form.get("plan", u.plan)
    u.active = request.form.get("active") == "on"
    u.is_admin = request.form.get("is_admin") == "on"

    if new_email != u.email and User.query.filter_by(email=new_email).first():
        flash("E-mail já em uso.", "warning")
        return redirect(url_for("admin_bp.admin"))
    u.email = new_email

    new_pwd = request.form.get("password")
    if new_pwd:
        u.set_password(new_pwd)

    db.session.commit()
    flash("Usuário atualizado.", "success")
    return redirect(url_for("admin_bp.admin"))

# ---------------- ADMIN: Planos ----------------
@admin_bp.route("/admin/plans/create", methods=["POST"])
@admin_required
def admin_plans_create():
    slug = request.form.get("slug")
    name = request.form.get("name")
    price = request.form.get("price", "0").replace(",", ".")
    limits = request.form.get("limits", "")
    active = request.form.get("active") == "on"

    if not slug or not name:
        flash("Slug e nome são obrigatórios.", "warning")
        return redirect(url_for("admin_bp.admin"))

    from ...models import Plan
    if Plan.query.filter_by(slug=slug).first():
        flash("Slug já utilizado.", "warning")
        return redirect(url_for("admin_bp.admin"))

    p = Plan(slug=slug, name=name, price=Decimal(price or "0"), limits=limits, active=active)
    db.session.add(p); db.session.commit()
    flash("Plano criado.", "success")
    return redirect(url_for("admin_bp.admin"))

@admin_bp.route("/admin/plans/<int:plan_id>/update", methods=["POST"])
@admin_required
def admin_plans_update(plan_id):
    from ...models import Plan
    p = Plan.query.get_or_404(plan_id)
    p.slug = request.form.get("slug", p.slug)
    p.name = request.form.get("name", p.name)
    price = request.form.get("price", "").replace(",", ".")
    if price:
        p.price = Decimal(price)
    p.limits = request.form.get("limits", p.limits)
    p.active = request.form.get("active") == "on"
    db.session.commit()
    flash("Plano atualizado.", "success")
    return redirect(url_for("admin_bp.admin"))

# ---------------- ADMIN: Configurações ----------------
@admin_bp.route("/admin/settings/update", methods=["POST"])
@admin_required
def admin_settings_update():
    set_setting("pix_key", request.form.get("pix_key", ""), "payments")
    set_setting("pix_receiver", request.form.get("pix_receiver", ""), "payments")
    set_setting("webhook_url", request.form.get("webhook_url", ""), "webhooks")
    set_setting("webhook_secret", request.form.get("webhook_secret", ""), "webhooks")
    flash("Configurações salvas.", "success")
    return redirect(url_for("admin_bp.admin"))

# ---------------- ADMIN: Pagamentos ----------------
@admin_bp.route("/admin/payments")
@admin_required
def admin_payments():
    q_status = request.args.get("status", "")
    q_email = request.args.get("email", "").strip()
    page = int(request.args.get("page", 1))
    per_page = 20

    qry = Payment.query.join(User)
    if q_status:
        qry = qry.filter(Payment.status == q_status)
    if q_email:
        qry = qry.filter(User.email.ilike(f"%{q_email}%"))

    pagination = qry.order_by(Payment.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    payments = pagination.items
    statuses = ["pago", "pendente", "falhou", "estornado"]

    return render_template(
        "admin_payments.html",
        payments=payments,
        pagination=pagination,
        q_status=q_status, q_email=q_email,
        statuses=statuses
    )

@admin_bp.route("/admin/payments/<int:pay_id>/update", methods=["POST"])
@admin_required
def admin_payment_update(pay_id):
    p = Payment.query.get_or_404(pay_id)
    p.status = request.form.get("status", p.status)
    p.provider = request.form.get("provider", p.provider)
    p.external_id = request.form.get("external_id", p.external_id)
    p.description = request.form.get("description", p.description)
    db.session.commit()
    flash("Pagamento atualizado.", "success")
    return redirect(url_for("admin_bp.admin_payments"))

@admin_bp.route("/admin/payments/create", methods=["POST"])
@admin_required
def admin_payment_create():
    email = request.form.get("email")
    amount = request.form.get("amount", "0").replace(",", ".")
    status = request.form.get("status", "pago")
    provider = request.form.get("provider", "manual")
    description = request.form.get("description", "")

    u = User.query.filter_by(email=email).first()
    if not u:
        flash("Usuário não encontrado para esse e-mail.", "warning")
        return redirect(url_for("admin_bp.admin_payments"))

    p = Payment(user_id=u.id, amount=Decimal(amount or "0"), status=status, provider=provider, description=description)
    db.session.add(p); db.session.commit()
    flash("Pagamento lançado.", "success")
    return redirect(url_for("admin_bp.admin_payments"))
