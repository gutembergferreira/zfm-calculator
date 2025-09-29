# app/models/payment_config.py
from __future__ import annotations
from ..extensions import db

class PaymentConfig(db.Model):
    __tablename__ = "payment_configs"
    id = db.Column(db.Integer, primary_key=True)
    # habilitar meios
    enable_pix  = db.Column(db.Boolean, default=True)
    enable_card = db.Column(db.Boolean, default=True)

    # credenciais (armazene chaves públicas; use .env para secretas)
    provider = db.Column(db.String(32), default="stripe")  # ou 'pagarme', 'gerencianet' etc.
    pix_key = db.Column(db.String(140))
    webhook_url = db.Column(db.String(255))
    webhook_secret = db.Column(db.String(255))
