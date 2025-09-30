# oraculoicms_app/blueprints/billing.py
from __future__ import annotations
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app, redirect, url_for, render_template, flash
import stripe

from ..decorators import login_required
from ..extensions import db
from ..models.user import User
from ..models.plan import Plan, Subscription
from ..models.user_quota import UserQuota
from .files import current_user  # helper que lê session['user']

bp = Blueprint("billing", __name__, url_prefix="/billing")

def _stripe():
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    return stripe

def _now():
    return datetime.now(timezone.utc)

def _get_or_create_sub(user: User) -> Subscription:
    sub = Subscription.query.filter_by(user_id=user.id).first()
    if not sub:
        # cria placeholder
        plan = Plan.query.filter_by(active=True).first()
        sub = Subscription(user_id=user.id, plan_id=plan.id if plan else None, provider="stripe")
        db.session.add(sub)
        db.session.commit()
    return sub

@bp.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout_choose():
    """Página para o usuário escolher plano e ciclo antes de ir ao Stripe."""
    plans = Plan.query.filter_by(active=True).all()
    if request.method == "POST":
        plan_id = int(request.form.get("plan_id"))
        cycle = request.form.get("cycle", "monthly")
        plan = Plan.query.get_or_404(plan_id)
        return redirect(url_for("billing.checkout", plan_slug=plan.slug, cycle=("monthly" if cycle=='monthly' else 'yearly')))
    return render_template("checkout.html", plans=plans)

@bp.route("/checkout/<plan_slug>/<cycle>")
@login_required
def checkout(plan_slug: str, cycle: str):
    """Cria a Stripe Checkout Session (modo assinatura)."""
    cycle = "monthly" if cycle not in ("monthly", "yearly") else cycle
    plan = Plan.query.filter_by(slug=plan_slug, active=True).first_or_404()
    price_id = plan.stripe_price_monthly_id if cycle == "monthly" else plan.stripe_price_yearly_id
    if not price_id:
        flash("Plano sem price_id do Stripe configurado.", "warning")
        return redirect(url_for("billing.checkout_choose"))

    s = _stripe()
    user = current_user() if callable(current_user) else current_user
    # cria/recupera Customer
    sub = _get_or_create_sub(user)
    if not sub.provider_cust_id:
        cust = s.Customer.create(email=user.email, name=user.name, metadata={"user_id": user.id})
        sub.provider_cust_id = cust.id
        db.session.add(sub); db.session.commit()

    # trial (opcional, conforme plan.trial_days)
    params = {
        "mode": "subscription",
        "customer": sub.provider_cust_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": current_app.config["STRIPE_SUCCESS_URL"],
        "cancel_url": current_app.config["STRIPE_CANCEL_URL"],
        "allow_promotion_codes": True,
    }
    if plan.trial_days and plan.trial_days > 0:
        params["subscription_data"] = {"trial_period_days": int(plan.trial_days)}

    sess = s.checkout.Session.create(**params)
    return redirect(sess.url, code=303)

@bp.route("/portal")
@login_required
def portal():
    """Redireciona para o Billing Portal da Stripe para gerenciar a assinatura."""
    s = _stripe()
    user = current_user() if callable(current_user) else current_user
    sub = _get_or_create_sub(user)
    if not sub.provider_cust_id:
        flash("Cliente não encontrado no Stripe.", "warning")
        return redirect(url_for("billing.checkout_choose"))
    portal = s.billing_portal.Session.create(customer=sub.provider_cust_id, return_url=url_for("core.dashboard", _external=True))
    return redirect(portal.url, code=303)

@bp.route("/sucesso")
@login_required
def sucesso():
    flash("Pagamento/assinatura criada com sucesso. Aguarde a confirmação.", "success")
    return render_template("billing_success.html")

@bp.route("/cancelado")
@login_required
def cancelado():
    flash("Fluxo de checkout cancelado.", "warning")
    return render_template("billing_cancel.html")

# -------- Stripe Webhook --------
def _on_subscription_change(customer_id: str, subscription_id: str):
    s = _stripe()
    # lê subscription do Stripe
    subs = s.Subscription.retrieve(subscription_id)
    price = subs["items"]["data"][0]["price"]
    # plan resolve pelo price.id salvo
    plan = Plan.query.filter(
        (Plan.stripe_price_monthly_id == price["id"]) | (Plan.stripe_price_yearly_id == price["id"])
    ).first()
    # encontra sub local
    sub = Subscription.query.filter_by(provider_cust_id=customer_id).first()
    if not sub:
        # fallback por customer_id
        sub = Subscription(provider="stripe")
        db.session.add(sub)

    # vincula usuário por metadata do customer se ainda não existir
    cust = s.Customer.retrieve(customer_id)
    user = User.query.filter_by(email=cust.get("email")).first()

    if user and plan:
        sub.user_id = user.id
        sub.plan_id = plan.id
        sub.provider = "stripe"
        sub.provider_sub_id = subscription_id
        sub.provider_cust_id = customer_id
        sub.status = subs.get("status") or "active"
        sub.billing_cycle = "year" if price.get("recurring",{}).get("interval") == "year" else "month"
        sub.amount_cents = int(price.get("unit_amount") or 0)
        # períodos
        if subs.get("current_period_start"):
            sub.period_start = datetime.fromtimestamp(subs["current_period_start"], tz=timezone.utc)
        if subs.get("current_period_end"):
            sub.period_end = datetime.fromtimestamp(subs["current_period_end"], tz=timezone.utc)
        if subs.get("trial_end"):
            sub.trial_end = datetime.fromtimestamp(subs["trial_end"], tz=timezone.utc)

        # Atualiza o 'plano' textual no usuário (compatibilidade com seu schema atual)
        user.plan = plan.slug
        db.session.add(user)

        # opcional: reset de cotas ao iniciar ciclo
        _ensure_quota_reset(user.id)

    db.session.add(sub)
    db.session.commit()

def _ensure_quota_reset(user_id: int):
    q = UserQuota.query.filter_by(user_id=user_id).first()
    if not q:
        return
    # zera contadores do mês
    q.month_uploads = 0
    q.month_ref = datetime.utcnow().strftime("%Y-%m")
    db.session.add(q)

@bp.route("/webhook", methods=["POST"])  # configure endpoint no Dashboard da Stripe
def stripe_webhook():
    s = _stripe()
    payload = request.data
    sig = request.headers.get("Stripe-Signature", "")
    secret = current_app.config["STRIPE_WEBHOOK_SECRET"]
    try:
        event = s.Webhook.construct_event(payload, sig, secret)
    except Exception:
        current_app.logger.exception("Webhook signature error")
        return "bad signature", 400

    typ = event["type"]
    data = event["data"]["object"]
    if typ == "checkout.session.completed":
        _on_subscription_change(data.get("customer"), data.get("subscription"))
    elif typ in ("customer.subscription.updated", "customer.subscription.created"):
        _on_subscription_change(data.get("customer"), data.get("id"))
    elif typ == "invoice.paid":
        # ok renovar
        pass
    elif typ == "invoice.payment_failed" or typ == "customer.subscription.deleted":
        # marcar como inadimplente/cancelado
        sub = Subscription.query.filter_by(provider_cust_id=data.get("customer")).first()
        if sub:
            sub.status = "past_due" if typ == "invoice.payment_failed" else "canceled"
            db.session.add(sub); db.session.commit()
    return jsonify(received=True)