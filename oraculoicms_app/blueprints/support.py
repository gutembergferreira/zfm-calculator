from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from ..decorators import login_required
from ..extensions import db
from ..models.support import KBArticle, VideoTutorial, FeedbackMessage, SurveyCampaign, SurveyQuestion, SurveyResponse, SurveyAnswer
from ..models.user import User
from ..blueprints.files import current_user  # já existe

bp = Blueprint("support", __name__)

@bp.route("/suporte")
@login_required
def help_center():
    q = (request.args.get("q") or "").strip()
    articles = KBArticle.query.filter_by(is_published=True).order_by(KBArticle.order.asc(), KBArticle.created_at.desc())
    if q:
        like = f"%{q}%"
        articles = articles.filter(db.or_(KBArticle.title.ilike(like), KBArticle.body_html.ilike(like), KBArticle.tags.ilike(like)))
    articles = articles.limit(20).all()

    videos = VideoTutorial.query.filter_by(is_published=True).order_by(VideoTutorial.order.asc(), VideoTutorial.created_at.desc()).limit(12).all()

    # campanha ativa (primeira aberta)
    camp = SurveyCampaign.query.filter_by(active=True).first()
    has_campaign = False
    if camp and camp.is_open():
        already = SurveyResponse.query.filter_by(campaign_id=camp.id, user_id=current_user().id).first()
        has_campaign = not bool(already)

    return render_template("support/index.html", q=q, articles=articles, videos=videos, campaign=camp if has_campaign else None)

@bp.route("/suporte/feedback", methods=["POST"])
@login_required
def send_feedback():
    cat = (request.form.get("category") or "").lower()
    subject = (request.form.get("subject") or "").strip()
    message = (request.form.get("message") or "").strip()
    if cat not in ("sugestao","erro","comentario","suporte"):
        flash("Categoria inválida.", "warning"); return redirect(url_for("support.help_center"))
    if not subject or not message:
        flash("Preencha assunto e mensagem.", "warning"); return redirect(url_for("support.help_center"))

    fb = FeedbackMessage(user_id=current_user().id, category=cat, subject=subject, message=message)
    db.session.add(fb); db.session.commit()
    flash("Mensagem enviada. Obrigado!", "success")
    return redirect(url_for("support.help_center"))

@bp.route("/suporte/pesquisa")
@login_required
def survey_start():
    camp = SurveyCampaign.query.filter_by(active=True).first()
    if not camp or not camp.is_open():
        flash("Não há pesquisa ativa no momento.", "info"); return redirect(url_for("support.help_center"))
    # se já respondeu, redireciona
    if SurveyResponse.query.filter_by(campaign_id=camp.id, user_id=current_user().id).first():
        flash("Você já respondeu esta pesquisa. Obrigado!", "info")
        return redirect(url_for("support.help_center"))
    qs = camp.questions
    return render_template("support/survey.html", camp=camp, qs=qs)

@bp.route("/suporte/pesquisa", methods=["POST"])
@login_required
def survey_submit():
    campaign_id = int(request.form.get("campaign_id"))
    camp = SurveyCampaign.query.get_or_404(campaign_id)
    if not camp.is_open():
        flash("Pesquisa encerrada.", "warning"); return redirect(url_for("support.help_center"))

    # impede duplo envio
    if SurveyResponse.query.filter_by(campaign_id=camp.id, user_id=current_user().id).first():
        flash("Você já respondeu esta pesquisa.", "info"); return redirect(url_for("support.help_center"))

    resp = SurveyResponse(campaign_id=camp.id, user_id=current_user().id)
    db.session.add(resp); db.session.flush()

    # perguntas => inputs: rating-<id> e comment-<id>
    for q in camp.questions:
        rating = int(request.form.get(f"rating-{q.id}") or 0)
        comment = (request.form.get(f"comment-{q.id}") or "").strip()
        if q.required and not (1 <= rating <= 5):
            db.session.rollback()
            flash("Responda todas as perguntas obrigatórias.", "warning")
            return redirect(url_for("support.survey_start"))
        if 1 <= rating <= 5:
            db.session.add(SurveyAnswer(response_id=resp.id, question_id=q.id, rating=rating, comment=comment or None))

    db.session.commit()
    flash("Obrigado! Suas respostas foram registradas.", "success")
    return redirect(url_for("support.help_center"))
