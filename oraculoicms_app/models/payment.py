# app/models/payment.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime
from ..extensions import db

class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="pago")  # pago, pendente, falhou, estornado
    provider = db.Column(db.String(30), default="manual")              # pix, card, manual
    external_id = db.Column(db.String(120))
    description = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
