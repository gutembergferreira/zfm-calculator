from flask import Blueprint, request, jsonify, current_app, redirect, url_for, render_template, flash
import stripe
import datetime as dt

from .files import current_user
from ..decorators import login_required
from ..extensions import db
from ..models import UserQuota
from ..models.plan import Plan, Subscription

bp = Blueprint("billing", __name__, url_prefix="/billing")

def _stripe():
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    return stripe

def _get_or_create_sub(user):
    sub = Subscription.query.filter_by(user_id=user.id).first()
    if not sub:
        sub = Subscription(user_id=user.id)
        db.session.add(sub); db.session.commit()
    return sub

@bp.route("/checkout/<plan_slug>/<cycle>")
@login_required
def checkout(plan_slug, cycle):
    """
    cycle: 'monthly' ou 'yearly'
    """
    plan = Plan.query.filter_by(slug=plan_slug, active=True).first_or_404()
    price_id = plan.stripe_price_monthly_id if cycle == "monthly" else plan.stripe_price_yearly_id
    if not price_id:
        flash("Plano sem preço Stripe configurado.", "warning")
        return redirect(url_for("core.index"))

    stripe_ = _stripe()
    user = current_user() if callable(current_user) else current_user

    # Cria/recupera um Customer
    sub = _get_or_create_sub(user)
    if not sub.stripe_customer_id:
        customer = stripe_.Customer.create(email=user.email or None, name=user.name or None)
        sub.stripe_customer_id = customer.id
        db.session.add(sub); db.session.commit()

    # Trial controlado no Stripe via price trial ou via subscription_data
    trial_days = plan.trial_days or 0
    params = {
        "mode": "subscription",
        "customer": sub.stripe_customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": current_app.config["STRIPE_SUCCESS_URL"],
        "cancel_url": current_app.config["STRIPE_CANCEL_URL"],
        "allow_promotion_codes": True,
    }
    if trial_days > 0:
        params["subscription_data"] = {"trial_period_days": trial_days}

    sess = stripe_.Checkout.Session.create(**params)
    return redirect(sess.url, code=303)

@bp.route("/portal")
@login_required
def portal():
    stripe_ = _stripe()
    user = current_user
    sub = _get_or_create_sub(user)
    if not sub.stripe_customer_id:
        flash("Nenhuma assinatura encontrada para acessar o Portal.", "warning")
        return redirect(url_for("core.index"))
    portal = stripe_.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=url_for("core.index", _external=True),
    )
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

# ——— WEBHOOK ———
@bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    stripe_ = _stripe()
    payload = request.data
    sig = request.headers.get("Stripe-Signature", "")
    secret = current_app.config["STRIPE_WEBHOOK_SECRET"]
    try:
        event = stripe_.Webhook.construct_event(payload, sig, secret)
    except Exception as e:
        current_app.logger.exception("Webhook signature error")
        return "bad signature", 400

    typ = event["type"]
    data = event["data"]["object"]

    # checkout.session.completed -> cria/atualiza subscription local
    if typ == "checkout.session.completed":
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        _on_subscription_change(customer_id, subscription_id)

    # customer.subscription.updated / created
    if typ in ("customer.subscription.updated", "customer.subscription.created"):
        subscription_id = data.get("id")
        customer_id = data.get("customer")
        _on_subscription_change(customer_id, subscription_id, data)

    # invoice.paid / invoice.payment_failed => opcional log
    return "ok", 200

def _on_subscription_change(customer_id, subscription_id, stripe_sub_obj=None):
    from ..models.user import User
    stripe_ = _stripe()
    if not stripe_sub_obj:
        stripe_sub_obj = stripe_.Subscription.retrieve(subscription_id, expand=["items.data.price.product"])

    # encontra o user pela subscription.customer
    sub = Subscription.query.filter_by(stripe_customer_id=customer_id).first()
    if not sub:
        # fallback: achar por subscription id
        sub = Subscription.query.filter_by(stripe_subscription_id=subscription_id).first()
    if not sub:
        current_app.logger.warning("Subscription local não encontrada: %s", subscription_id)
        return

    sub.stripe_subscription_id = subscription_id
    sub.status = stripe_sub_obj.get("status")
    cpe = stripe_sub_obj.get("current_period_end")
    sub.current_period_end = dt.datetime.utcfromtimestamp(cpe) if cpe else None
    sub.cancel_at_period_end = bool(stripe_sub_obj.get("cancel_at_period_end"))

    # identifica o plano pelo price
    items = stripe_sub_obj.get("items", {}).get("data", [])
    price_id = items[0]["price"]["id"] if items else None
    plan = Plan.query.filter(
        (Plan.stripe_price_monthly_id == price_id) | (Plan.stripe_price_yearly_id == price_id)
    ).first()

    if plan:
        sub.plan_id = plan.id
        # aplica plano ao usuário
        user = User.query.get(sub.user_id)
        if user:
            user.plan_id = plan.id
            db.session.add(user)

            # opcional: reset de quota mensal se começou trial ou período
            _ensure_quota_reset(user.id, plan)

    db.session.add(sub)
    db.session.commit()

def _ensure_quota_reset(user_id:int, plan:Plan):
    # Resetar contadores mensais quando troca de plano (opcional)
    q = UserQuota.query.filter_by(user_id=user_id).first()
    if not q:
        return
    q.month_uploads = 0
    q.month_ref = dt.datetime.utcnow().strftime("%Y-%m")
    db.session.add(q)
