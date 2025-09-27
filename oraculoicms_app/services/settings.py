# app/services/settings.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from ..extensions import db
from ..models import Setting

def get_setting(key: str, group: str = "payments", default: str = "") -> str:
    s = Setting.query.filter_by(group=group, key=key).first()
    return s.value if s else default

def set_setting(key: str, value: str, group: str = "payments") -> None:
    s = Setting.query.filter_by(group=group, key=key).first()
    if not s:
        s = Setting(group=group, key=key, value=value)
        db.session.add(s)
    else:
        s.value = value
    db.session.commit()
