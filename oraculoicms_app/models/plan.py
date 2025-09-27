# app/models/plan.py
from __future__ import annotations
from datetime import datetime
from ..extensions import db

class Plan(db.Model):
    __tablename__ = "plans"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False)   # ex: basic, pro, ent
    name = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    limits = db.Column(db.String(255), default="")

    # NOVOS LIMITES
    max_files = db.Column(db.Integer, default=100)
    max_storage_mb = db.Column(db.Integer, default=200)
    max_monthly_files = db.Column(db.Integer, default=100)
    max_monthly_storage_mb = db.Column(db.Integer, default=200)

    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
