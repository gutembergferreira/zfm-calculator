# app/models/plan.py
from __future__ import annotations
from datetime import datetime, timedelta
from ..extensions import db

class Plan(db.Model):
    __tablename__ = "plans"
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description_md = db.Column(db.Text)             # para exibir na landing
    active = db.Column(db.Boolean, default=True)

    # preços (R$) — sempre em centavos para evitar float
    price_month_cents = db.Column(db.Integer, default=0)
    price_year_cents  = db.Column(db.Integer, default=0)
    currency = db.Column(db.String(8), default="BRL")

    # trial
    trial_days = db.Column(db.Integer, default=0)
    trial_xml_quota = db.Column(db.Integer, default=0)

    # limites
    max_files            = db.Column(db.Integer, default=0)      # armazenamento simultâneo
    max_storage_mb       = db.Column(db.Integer, default=0)
    max_uploads_month    = db.Column(db.Integer, default=0)

    # integração opcional com PSP (ex.: IDs de “price” do Stripe)
    provider_month_price_id = db.Column(db.String(120))
    provider_year_price_id  = db.Column(db.String(120))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Subscription(db.Model):
    __tablename__ = "subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("plans.id"), nullable=False)

    status = db.Column(db.String(20), default="incomplete")  # incomplete, trialing, active, past_due, canceled, unpaid
    period_start = db.Column(db.DateTime)
    period_end   = db.Column(db.DateTime)     # data de expiração/renovação
    trial_end    = db.Column(db.DateTime)     # se houver trial

    # pagamento atual
    billing_cycle = db.Column(db.String(10), default="month")  # month/year
    amount_cents  = db.Column(db.Integer, default=0)

    # chaves do provedor
    provider = db.Column(db.String(32))         # 'stripe', 'gerencianet', 'pagarme', etc.
    provider_sub_id = db.Column(db.String(120))
    provider_cust_id = db.Column(db.String(120))

    # última cobrança
    last_invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey("subscriptions.id"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    amount_cents = db.Column(db.Integer, default=0)
    currency = db.Column(db.String(8), default="BRL")
    status = db.Column(db.String(20), default="pending")  # pending, paid, failed, canceled
    method = db.Column(db.String(16))  # 'pix', 'card'
    # PSP refs
    provider = db.Column(db.String(32))
    provider_invoice_id = db.Column(db.String(120))
    provider_qr_code = db.Column(db.Text)     # PIX dinâmico (opcional)
    provider_qr_image_b64 = db.Column(db.Text)
    provider_checkout_url = db.Column(db.Text) # cartão link-checkout (se usar)
    paid_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
