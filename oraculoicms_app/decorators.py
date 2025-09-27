# zfm_app/decorators.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from functools import wraps
from flask import session, flash, redirect, url_for, request

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            flash("Faça login para acessar.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user = session.get("user")
        if not user:
            flash("Faça login para acessar.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if not user.get("is_admin"):
            flash("Acesso restrito ao administrador.", "danger")
            return redirect(url_for("core.dashboard"))
        return view_func(*args, **kwargs)
    return wrapper
