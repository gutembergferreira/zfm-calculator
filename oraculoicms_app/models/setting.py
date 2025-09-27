# app/models/setting.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime
from ..extensions import db

class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    group = db.Column(db.String(50), index=True)               # ex: payments, webhooks
    key = db.Column(db.String(100), index=True, nullable=False)
    value = db.Column(db.Text, default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("group", "key", name="uq_settings_group_key"),
    )
