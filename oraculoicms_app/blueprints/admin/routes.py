# app/blueprints/admin/routes.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from decimal import Decimal
from flask import render_template, request, redirect, url_for, flash, session,current_app
from ..admin import admin_bp
from ...decorators import admin_required
from ...extensions import db
from ...models import User, Plan, Payment, Subscription
from ...services.settings import get_setting, set_setting

import os, platform, socket, time
from pathlib import Path
from datetime import datetime
import stripe
from sqlalchemy import text, func
from dotenv import dotenv_values, set_key


def _s():
    stripe.api_key = current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    return stripe

def _first(iterable):
    for x in iterable or []:
        return x
    return None


def _to_cents(v: str | None) -> int:
    if not v:
        return 0
    v = v.strip().replace('.', '').replace(',', '.')
    return int(Decimal(v) * 100)

def _system_snapshot():
    # Postgres
    try:
        from ...extensions import db
        db.session.execute(text("SELECT 1"))
        pg_ok, pg_detail = True, "Conexão OK"
    except Exception as e:
        pg_ok, pg_detail = False, str(e)

    # Stripe
    sk = current_app.config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    st_ok, st_detail = False, "Chave não configurada"
    if sk:
        try:
            stripe.api_key = sk
            # chamada leve para validar credenciais:
            stripe.Balance.retrieve()
            st_ok, st_detail = True, "Credenciais válidas"
        except Exception as e:
            st_ok, st_detail = False, str(e)

    # Matrizes do motor
    try:
        from ...services.sheets_service import get_matrices
        matrices = get_matrices() or {}
        df_sources = matrices.get("sources")
        total = 0 if df_sources is None else len(df_sources.index)
        gs_ok, gs_detail = True, f"{total} fontes carregadas"
    except Exception as e:
        gs_ok, gs_detail = False, str(e)

    statuses = [
        dict(name="Postgres", ok=pg_ok, detail=pg_detail),
        dict(name="Stripe", ok=st_ok, detail=st_detail),
        dict(name="Parâmetros", ok=gs_ok, detail=gs_detail),
    ]

    # Server info
    server = dict(
        hostname=socket.gethostname(),
        os=f"{platform.system()} {platform.release()}",
        arch=platform.machine(),
        python=platform.python_version(),
        timezone=time.tzname[0] if time.tzname else "UTC",
        started_at=current_app.config.get("STARTED_AT"),
        pid=os.getpid()
    )
    return statuses, server

def _config_snapshot():
    """
    Busca os mesmos dados que a view de config.html usa.
    Adeque de acordo com seu módulo de sheets.
    """
    try:
        from ...services.sheets_service import get_matrices
        matrices = get_matrices() or {}
        df_sources = matrices.get("sources")
        sources_count = 0 if df_sources is None else len(df_sources.index)
    except Exception as e:
        current_app.logger.warning("Config snapshot error: %s", e)
        sources_count = 0

    sheet_title = "Banco de dados"
    service_email = None
    worksheets = []
    updated_at = datetime.utcnow().isoformat(timespec="seconds")
    return sheet_title, service_email, worksheets, updated_at, sources_count

# ---------------- ADMIN: Painel ----------------
@admin_bp.route("/admin")
@admin_required
def admin():
    users = User.query.order_by(User.created_at.desc()).all()
    plans = (
        Plan.query
        .order_by(func.coalesce(Plan.price_month_cents, 0).asc())
        .all()
    )
    sys_status, server_info = _system_snapshot()
    sheet_title, service_email, worksheets, updated_at, sources_count = _config_snapshot()

    # Configs (exibição similar ao config.html; ajuste as chaves que quer mostrar)
    cfg_keys = [
        "SQLALCHEMY_DATABASE_URI",
        "STRIPE_PUBLISHABLE_KEY",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_SUCCESS_URL",
        "STRIPE_CANCEL_URL",
        "FLASK_ENV",
        "DEBUG",
    ]
    app_cfg = {k: current_app.config.get(k) for k in cfg_keys}

    # .env atual
    env_path = Path(current_app.root_path).parent / ".env"
    env_vars = dotenv_values(env_path) if env_path.exists() else {}

    return render_template(
        "admin_panel.html",
        users=users,
        plans=plans,
        sys_status=sys_status,
        server_info=server_info,
        sheet_title=sheet_title,
        service_email=service_email,
        worksheets=worksheets,
        updated_at=updated_at,
        sources_count=sources_count,
        app_cfg=app_cfg,
        env_vars=env_vars,
        env_path=str(env_path),
    )

@admin_bp.route("/admin/env", methods=["POST"])
@admin_required
def admin_env_update():
    env_path = Path(current_app.root_path).parent / ".env"
    env_path.touch(exist_ok=True)

    keys = request.form.getlist("key")
    vals = request.form.getlist("value")

    # grava usando python-dotenv
    for k, v in zip(keys, vals):
        k = (k or "").strip()
        if not k:
            continue
        set_key(str(env_path), k, v or "")
        # também joga no os.environ para uso imediato (parcial)
        os.environ[k] = v or ""

    flash("Arquivo .env atualizado. Reinicie a aplicação para aplicar 100%.", "success")
    return redirect(url_for("admin_bp.admin") + "#system")

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
    p = Plan(
        slug=request.form.get("slug", "").strip(),
        name=request.form.get("name", "").strip(),
        description_md=request.form.get("description_md", "").strip(),
        active=(request.form.get("active") == "on"),
        price_month_cents=_to_cents(request.form.get("price_month")),
        price_year_cents=_to_cents(request.form.get("price_year")),
        stripe_price_monthly_id=request.form.get("stripe_price_monthly_id") or None,
        stripe_price_yearly_id=request.form.get("stripe_price_yearly_id") or None,
        trial_days=int(request.form.get("trial_days") or 0),
        trial_xml_quota=int(request.form.get("trial_xml_quota") or 0),
        max_files=int(request.form.get("max_files") or 0),
        max_storage_mb=int(request.form.get("max_storage_mb") or 0),
        max_uploads_month=int(request.form.get("max_uploads_month") or 0),
    )
    db.session.add(p)
    db.session.commit()
    flash("Plano criado.", "success")
    return redirect(url_for("admin_bp.admin"))


@admin_bp.route("/admin/plans/<int:plan_id>/update", methods=["POST"])
@admin_required
def admin_plans_update(plan_id):
    p = Plan.query.get_or_404(plan_id)
    p.slug = request.form.get("slug", p.slug).strip()
    p.name = request.form.get("name", p.name).strip()
    p.description_md = request.form.get("description_md", p.description_md) or ""
    p.active = (request.form.get("active") == "on")

    # preços e ids stripe
    pm = request.form.get("price_month")
    py = request.form.get("price_year")
    if pm is not None:
        p.price_month_cents = _to_cents(pm)
    if py is not None:
        p.price_year_cents = _to_cents(py)

    p.stripe_price_monthly_id = request.form.get("stripe_price_monthly_id") or None
    p.stripe_price_yearly_id  = request.form.get("stripe_price_yearly_id") or None

    # trial e limites
    p.trial_days = int(request.form.get("trial_days") or p.trial_days or 0)
    p.trial_xml_quota = int(request.form.get("trial_xml_quota") or p.trial_xml_quota or 0)
    p.max_files = int(request.form.get("max_files") or p.max_files or 0)
    p.max_storage_mb = int(request.form.get("max_storage_mb") or p.max_storage_mb or 0)
    p.max_uploads_month = int(request.form.get("max_uploads_month") or p.max_uploads_month or 0)

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

# -------- LISTAGEM VIA STRIPE --------
@admin_bp.route("/admin/payments")
@admin_required
def admin_payments():
    s = _s()
    q_status = (request.args.get("status") or "").strip()  # paid / open / draft / uncollectible / void
    q_email = (request.args.get("email") or "").strip()
    starting_after = request.args.get("starting_after") or None
    ending_before = request.args.get("ending_before") or None
    limit = 20

    # Descobre um customer pelo e-mail (se informado)
    customer_id = None
    if q_email:
        try:
            # Stripe Customer Search (se habilitado). Fallback: pega o primeiro encontrado.
            res = s.Customer.search(query=f"email:'{q_email}'", limit=1)
            cust = _first(res.data)
            if cust:
                customer_id = cust.id
        except Exception:
            # fallback simples: lista clientes e filtra por e-mail (menos eficiente)
            res = s.Customer.list(limit=100)
            for c in res.auto_paging_iter():
                if (c.email or "").lower() == q_email.lower():
                    customer_id = c.id
                    break

    # Monta parâmetros para Invoice list
    params = {
        "limit": limit,
        "expand": ["data.customer", "data.subscription", "data.payment_intent"],
    }
    if starting_after:
        params["starting_after"] = starting_after
    if ending_before:
        params["ending_before"] = ending_before
    if customer_id:
        params["customer"] = customer_id
    if q_status:
        params["status"] = q_status  # valores válidos: draft, open, paid, uncollectible, void

    invoices = s.Invoice.list(**params)

    # Prepara paginação estilo "cursor"
    next_cursor = invoices.data[-1].id if invoices.has_more and invoices.data else None
    prev_cursor = invoices.data[0].id if invoices.data else None  # para ending_before

    # Mapeia status legíveis
    statuses = ["paid", "open", "draft", "uncollectible", "void"]

    return render_template(
        "admin_payments.html",
        invoices=invoices.data,
        has_more=invoices.has_more,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        q_status=q_status,
        q_email=q_email,
        statuses=statuses
    )

# -------- VALIDAR (SYNC) UMA FATURA DA STRIPE E ATUALIZAR O BANCO LOCAL --------
@admin_bp.route("/admin/payments/<invoice_id>/validate", methods=["POST"])
@admin_required
def admin_payment_validate(invoice_id):
    s = _s()

    # Buscamos a Invoice com expansões úteis. Ainda assim, alguns campos podem não existir.
    inv = s.Invoice.retrieve(
        invoice_id,
        expand=[
            "customer",
            "subscription",
            "payment_intent",
            "lines.data.price.product",
        ],
    )

    # ---------- Customer / usuário ----------
    cust_obj = getattr(inv, "customer", None)  # pode ser StripeObject, string (ID) ou ausente
    if isinstance(cust_obj, str):
        try:
            cust_obj = s.Customer.retrieve(cust_obj)
        except Exception:
            cust_obj = None

    email = getattr(cust_obj, "email", None) if cust_obj else None
    user = User.query.filter_by(email=email).first() if email else None
    if not user:
        flash("Usuário não encontrado para o e-mail do cliente Stripe.", "warning")
        return redirect(url_for("admin_bp.admin_payments", email=email or ""))

    # ---------- Subscription (opcional/ausente) ----------
    sub_obj = None
    sub_val = getattr(inv, "subscription", None)  # pode ser ausente, None, ID ou objeto
    if isinstance(sub_val, str):
        # veio só o ID
        try:
            sub_obj = s.Subscription.retrieve(sub_val)
        except Exception:
            sub_obj = None
    elif sub_val is not None:
        # já é objeto expandido
        sub_obj = sub_val

    # ---------- Price / plano ----------
    price_id = None
    product_name = None
    try:
        first_line = inv.lines.data[0] if (inv.lines and inv.lines.data) else None
        if first_line and getattr(first_line, "price", None):
            price = first_line.price
            price_id = getattr(price, "id", None)
            # tenta um nome “amigável” pra exibição, se precisar:
            product_name = getattr(price, "nickname", None) or (
                getattr(price, "product", None).get("name") if isinstance(price.product, dict) else None
            )
    except Exception:
        pass

    plan = None
    if price_id:
        plan = Plan.query.filter(
            (Plan.stripe_price_monthly_id == price_id) | (Plan.stripe_price_yearly_id == price_id)
        ).first()

    # ---------- Atualiza/Cria assinatura local (se aplicável) ----------
    subs_rec = None
    provider_cust_id = getattr(cust_obj, "id", None) if cust_obj else None
    if provider_cust_id:
        subs_rec = Subscription.query.filter_by(provider_cust_id=provider_cust_id).first()
        if not subs_rec:
            subs_rec = Subscription(user_id=user.id, provider="stripe", provider_cust_id=provider_cust_id)
            db.session.add(subs_rec)

        subs_rec.provider_sub_id = getattr(sub_obj, "id", None) if sub_obj else subs_rec.provider_sub_id
        if plan:
            subs_rec.plan_id = plan.id
            user.plan = plan.slug  # seu User guarda o slug
            db.session.add(user)

        # status e períodos
        status_val = getattr(sub_obj, "status", None) if sub_obj else (getattr(inv, "status", None) or "paid")
        subs_rec.status = status_val

        # períodos (se houver subscription)
        from datetime import datetime
        if sub_obj and getattr(sub_obj, "current_period_start", None):
            subs_rec.period_start = datetime.utcfromtimestamp(sub_obj.current_period_start)
        if sub_obj and getattr(sub_obj, "current_period_end", None):
            subs_rec.period_end = datetime.utcfromtimestamp(sub_obj.current_period_end)

        db.session.add(subs_rec)

    # ---------- Registrar/atualizar Payment local ----------
    from decimal import Decimal
    amt = Decimal(((getattr(inv, "amount_paid", None) or getattr(inv, "amount_due", None) or 0)) / 100)

    pay = Payment.query.filter_by(provider="stripe", external_id=inv.id).first()
    if not pay:
        pay = Payment(
            user_id=user.id,
            amount=amt,
            status=("pago" if getattr(inv, "status", "") == "paid" else "pendente"),
            provider="stripe",
            external_id=inv.id,
            description=f"Invoice {getattr(inv, 'number', None) or inv.id}",
        )
        db.session.add(pay)
    else:
        pay.amount = amt
        pay.status = ("pago" if getattr(inv, "status", "") == "paid" else "pendente")
        pay.description = f"Invoice {getattr(inv, 'number', None) or inv.id}"
        db.session.add(pay)

    db.session.commit()
    flash("Pagamento/assinatura sincronizados com a Stripe.", "success")
    return redirect(url_for("admin_bp.admin_payments", email=email or ""))


# -------- REEMBOLSAR (REFUND) UMA COBRANÇA ----------
@admin_bp.route("/admin/payments/<invoice_id>/refund", methods=["POST"])
@admin_required
def admin_payment_refund(invoice_id):
    s = _s()
    inv = s.Invoice.retrieve(invoice_id, expand=["payment_intent", "charge"])
    charge_id = None
    if getattr(inv, "charge", None):
        charge_id = inv.charge
    elif getattr(inv, "payment_intent", None) and getattr(inv.payment_intent, "latest_charge", None):
        charge_id = inv.payment_intent.latest_charge

    if not charge_id:
        flash("Não foi possível localizar a cobrança (charge) dessa fatura para reembolso.", "warning")
        return redirect(url_for("admin_bp.admin_payments"))

    try:
        s.Refund.create(charge=charge_id)
        flash("Reembolso solicitado com sucesso.", "success")
    except Exception as e:
        flash(f"Falha ao reembolsar: {e}", "danger")
    return redirect(url_for("admin_bp.admin_payments"))

# -------- CANCELAR UMA ASSINATURA ----------
@admin_bp.route("/admin/subscriptions/<sub_id>/cancel", methods=["POST"])
@admin_required
def admin_subscription_cancel(sub_id):
    s = _s()
    at_period_end = request.form.get("at_period_end") == "on"
    try:
        s.Subscription.delete(sub_id) if not at_period_end else s.Subscription.modify(sub_id, cancel_at_period_end=True)
        # opcional: atualizar local
        subs_rec = Subscription.query.filter_by(provider_sub_id=sub_id).first()
        if subs_rec:
            subs_rec.status = "canceled" if not at_period_end else "active"  # ficará ativa até o fim do ciclo
            db.session.add(subs_rec); db.session.commit()
        flash("Assinatura cancelada.", "success")
    except Exception as e:
        flash(f"Falha ao cancelar: {e}", "danger")
    return redirect(url_for("admin_bp.admin_payments"))
