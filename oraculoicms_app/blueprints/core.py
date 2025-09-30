# zfm_app/blueprints/core.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import Blueprint, render_template, flash, redirect, url_for
from sqlalchemy import func

from oraculoicms_app.decorators import login_required
from oraculoicms_app.models import Plan, FeedbackMessage

bp = Blueprint("core", __name__)

@bp.route("/")
def index():
    plans = Plan.query.filter_by(active=True) \
        .order_by(func.coalesce(Plan.price_month_cents, 0).asc(), Plan.name.asc()).all()

    testimonials = FeedbackMessage.query \
        .filter_by(category="comentario", is_featured=True) \
        .order_by(FeedbackMessage.created_at.desc()) \
        .limit(6).all()

    return render_template("landing.html", plans=plans, testimonials=testimonials)

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


@bp.route("/me/purge-xmls", methods=["POST"])
@login_required
def purge_my_xmls():
    # Delete seus registros/arquivos do usuário atual:
    # NFe.query.filter_by(user_id=current_user.id).delete()
    # Upload.query.filter_by(user_id=current_user.id).delete()
    # db.session.commit()
    flash("Todos os seus XMLs foram removidos.", "success")
    return redirect(url_for("auth.account"))