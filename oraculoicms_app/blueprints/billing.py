# oraculoicms_app/blueprints/billing.py
from datetime import datetime, timedelta

from flask import Blueprint, request

from oraculoicms_app import db
from oraculoicms_app.blueprints.files import current_user, _get_quota
from oraculoicms_app.decorators import login_required
from oraculoicms_app.models import Plan
from oraculoicms_app.models.plan import Subscription, Invoice

bp = Blueprint("billing", __name__, url_prefix="/billing")

@bp.post("/checkout")
@login_required
def checkout():
    """
    body: plan_id, cycle=('month'|'year'), method=('pix'|'card')
    cria subscription/invoice e retorna dados p/ pagar (qr/checkout_url)
    """
    data = request.get_json() or {}
    plan_id = int(data.get("plan_id") or 0)
    cycle = (data.get("cycle") or "month").lower()
    method = (data.get("method") or "pix").lower()

    plan = Plan.query.get_or_404(plan_id)
    if not plan.active:
        return {"error": "Plano inativo"}, 400

    amount = plan.price_month_cents if cycle == "month" else plan.price_year_cents
    if amount <= 0:
        return {"error": "Plano sem preço configurado."}, 400

    # cria/atualiza subscription
    sub = (Subscription.query
           .filter_by(user_id=current_user().id, status.in_(["active","trialing","incomplete","past_due"]))
           .order_by(Subscription.id.desc()).first())
    if not sub:
        sub = Subscription(user_id=current_user().id, plan_id=plan.id, status="incomplete")
        db.session.add(sub); db.session.flush()
    else:
        sub.plan_id = plan.id
        sub.status = "incomplete"

    sub.billing_cycle = cycle
    sub.amount_cents = amount

    inv = Invoice(subscription_id=sub.id, user_id=current_user().id,
                  amount_cents=amount, method=method, provider="stripe")  # exemplo
    db.session.add(inv); db.session.commit()

    # chamar provedor
    if method == "pix":
        qr, img_b64, provider_invoice_id = create_pix_charge(inv, plan)  # implemente no gateway
        inv.provider_invoice_id = provider_invoice_id
        inv.provider_qr_code = qr
        inv.provider_qr_image_b64 = img_b64
        db.session.commit()
        return {"invoice_id": inv.id, "pix_qr": qr, "pix_img_b64": img_b64}

    elif method == "card":
        checkout_url, provider_invoice_id = create_card_checkout(inv, plan)  # implemente no gateway
        inv.provider_invoice_id = provider_invoice_id
        inv.provider_checkout_url = checkout_url
        db.session.commit()
        return {"invoice_id": inv.id, "checkout_url": checkout_url}

    return {"error": "Método inválido."}, 400

@bp.post("/webhook")
@csrf.exempt  # valide assinatura manualmente!
def webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature")  # ou cabeçalho do seu PSP
    # verify_signature(payload, sig, config.webhook_secret)  # implemente

    event = parse_event(payload)  # padronize o objeto vindo
    # esperado: kind ('invoice.paid', 'charge.paid'), provider_invoice_id, method, amount

    inv = Invoice.query.filter_by(provider_invoice_id=event.provider_invoice_id).first()
    if not inv:
        return "", 200

    if event.kind in ("invoice.paid","charge.paid"):
        inv.status = "paid"
        inv.paid_at = datetime.utcnow()
        db.session.add(inv)

        sub = Subscription.query.get(inv.subscription_id)
        now = datetime.utcnow()
        sub.period_start = now

        if sub.billing_cycle == "year":
            sub.period_end = now.replace(year=now.year+1)
        else:
            # adicionar 1 mês de forma segura:
            from dateutil.relativedelta import relativedelta
            sub.period_end = now + relativedelta(months=+1)

        # trial (opcional: somente na primeira ativação)
        plan = Plan.query.get(sub.plan_id)
        if plan.trial_days and sub.status == "incomplete":
            sub.trial_end = now + timedelta(days=plan.trial_days)
            sub.status = "trialing"
        else:
            sub.status = "active"

        # reset de quotas do mês (se você controla aqui)
        q = _get_quota(sub.user_id)
        q.month_uploads = 0
        db.session.add(q); db.session.add(sub)
        db.session.commit()

    return "", 200
