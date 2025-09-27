# zfm_app/blueprints/core.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import Blueprint, render_template
from oraculoicms_app.decorators import login_required

bp = Blueprint("core", __name__)

@bp.route("/")
def index():
    return render_template("landing.html")

@bp.route("/dashboard")
@login_required
def dashboard():
    stats = {
        "users": 128,
        "nfes_month": 4321,
        "mrr": 15349.90,
        "storage": "18.2 GB",
        "last_week": [12, 9, 8, 10, 6, 11, 13],
        "mrr_by_plan": {"Básico": 5200, "Pro": 9800, "Enterprise": 349.9}
    }
    return render_template("dashboard.html", stats=stats)

@bp.route("/support")
@login_required
def support():
    return render_template("support.html")

@bp.route("/leitorxml")
@login_required
def leitorxml():
    # aponta para sua página de upload/captura
    return render_template("index.html")
