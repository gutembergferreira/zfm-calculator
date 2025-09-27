# app/models/user_quota.py
from __future__ import annotations
from datetime import datetime
from ..extensions import db

class UserQuota(db.Model):
    __tablename__ = "user_quotas"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)

    files_count = db.Column(db.Integer, nullable=False, default=0)         # arquivos atualmente armazenados
    storage_bytes = db.Column(db.BigInteger, nullable=False, default=0)    # bytes atualmente armazenados

    # controle de uploads mês a mês
    month_uploads = db.Column(db.Integer, nullable=False, default=0)
    month_ref = db.Column(db.String(7), nullable=False, default=lambda: datetime.utcnow().strftime("%Y-%m"))  # ex: "2025-09"

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
