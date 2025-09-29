from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..decorators import login_required, admin_required  # se você tiver; senão use seu decorator de admin
from ..extensions import db
from ..models.support import KBArticle, VideoTutorial, FeedbackMessage, SurveyCampaign, SurveyQuestion, SurveyResponse, SurveyAnswer
from ..blueprints.files import current_user
from datetime import datetime

bp = Blueprint("support_admin", __name__, url_prefix="/admin/support")

def _is_admin():
    # ajuste conforme sua regra (ex.: current_user().is_admin)
    u = current_user()
    return bool(u and getattr(u, "is_admin", True))

def _guard():
    if not _is_admin():
        flash("Acesso restrito.", "warning")
        return redirect(url_for("core.index"))

@bp.route("/")
@login_required
def dashboard():
    g = _guard() or None
    total_fb = FeedbackMessage.query.count()
    abertos  = FeedbackMessage.query.filter(FeedbackMessage.status!="resolvido").count()
    camps = SurveyCampaign.query.order_by(SurveyCampaign.created_at.desc()).limit(5).all()
    return render_template("support/admin/dashboard.html", total_fb=total_fb, abertos=abertos, camps=camps)

# KB CRUD
@bp.route("/kb")
@login_required
def kb_list():
    _guard()
    rows = KBArticle.query.order_by(KBArticle.order.asc(), KBArticle.created_at.desc()).all()
    return render_template("support/admin/kb_list.html", rows=rows)

@bp.route("/kb/new", methods=["GET","POST"])
@login_required
def kb_new():
    _guard()
    if request.method == "POST":
        a = KBArticle(
            title=(request.form.get("title") or "").strip(),
            body_html=(request.form.get("body_html") or "").strip(),
            tags=(request.form.get("tags") or "").strip(),
            is_published=bool(request.form.get("is_published")),
            order=int(request.form.get("order") or 0),
        )
        db.session.add(a); db.session.commit()
        flash("Artigo criado.", "success"); return redirect(url_for("support_admin.kb_list"))
    return render_template("support/admin/kb_form.html", row=None)

@bp.route("/kb/<int:id>/edit", methods=["GET","POST"])
@login_required
def kb_edit(id):
    _guard()
    a = KBArticle.query.get_or_404(id)
    if request.method == "POST":
        a.title = (request.form.get("title") or "").strip()
        a.body_html = (request.form.get("body_html") or "").strip()
        a.tags = (request.form.get("tags") or "").strip()
        a.is_published = bool(request.form.get("is_published"))
        a.order = int(request.form.get("order") or 0)
        db.session.add(a); db.session.commit()
        flash("Atualizado.", "success"); return redirect(url_for("support_admin.kb_list"))
    return render_template("support/admin/kb_form.html", row=a)

@bp.route("/kb/<int:id>/delete", methods=["POST"])
@login_required
def kb_delete(id):
    _guard()
    a = KBArticle.query.get_or_404(id)
    db.session.delete(a); db.session.commit()
    flash("Excluído.", "info"); return redirect(url_for("support/admin.kb_list"))

# Vídeos CRUD (similar)
@bp.route("/videos")
@login_required
def vid_list():
    _guard()
    rows = VideoTutorial.query.order_by(VideoTutorial.order.asc(), VideoTutorial.created_at.desc()).all()
    return render_template("support/admin/vid_list.html", rows=rows)

@bp.route("/videos/new", methods=["GET","POST"])
@login_required
def vid_new():
    _guard()
    if request.method == "POST":
        v = VideoTutorial(
            title=(request.form.get("title") or "").strip(),
            embed_url=(request.form.get("embed_url") or "").strip(),
            is_published=bool(request.form.get("is_published")),
            order=int(request.form.get("order") or 0),
        )
        db.session.add(v); db.session.commit()
        flash("Vídeo adicionado.", "success"); return redirect(url_for("support_admin.vid_list"))
    return render_template("support/admin/vid_form.html", row=None)

@bp.route("/videos/<int:id>/edit", methods=["GET","POST"])
@login_required
def vid_edit(id):
    _guard()
    v = VideoTutorial.query.get_or_404(id)
    if request.method == "POST":
        v.title = (request.form.get("title") or "").strip()
        v.embed_url = (request.form.get("embed_url") or "").strip()
        v.is_published = bool(request.form.get("is_published"))
        v.order = int(request.form.get("order") or 0)
        db.session.add(v); db.session.commit()
        flash("Atualizado.", "success"); return redirect(url_for("support_admin.vid_list"))
    return render_template("support/admin/vid_form.html", row=v)

@bp.route("/videos/<int:id>/delete", methods=["POST"])
@login_required
def vid_delete(id):
    _guard()
    v = VideoTutorial.query.get_or_404(id)
    db.session.delete(v); db.session.commit()
    flash("Excluído.", "info"); return redirect(url_for("support/admin.vid_list"))

# Campanhas / Perguntas
@bp.route("/campaigns")
@login_required
def camp_list():
    _guard()
    rows = SurveyCampaign.query.order_by(SurveyCampaign.created_at.desc()).all()
    return render_template("support/admin/camp_list.html", rows=rows)

@bp.route("/campaigns/new", methods=["GET","POST"])
@login_required
def camp_new():
    _guard()
    if request.method == "POST":
        c = SurveyCampaign(
            title=(request.form.get("title") or "").strip(),
            description=(request.form.get("description") or "").strip(),
            active=bool(request.form.get("active")),
            starts_at=request.form.get("starts_at") or None,
            ends_at=request.form.get("ends_at") or None,
        )
        db.session.add(c); db.session.commit()
        flash("Campanha criada.", "success"); return redirect(url_for("support_admin.camp_list"))
    return render_template("support/admin/camp_form.html", row=None)

@bp.route("/campaigns/<int:id>/edit", methods=["GET","POST"])
@login_required
def camp_edit(id):
    _guard()
    c = SurveyCampaign.query.get_or_404(id)
    if request.method == "POST":
        c.title = (request.form.get("title") or "").strip()
        c.description = (request.form.get("description") or "").strip()
        c.active = bool(request.form.get("active"))
        c.starts_at = request.form.get("starts_at") or None
        c.ends_at = request.form.get("ends_at") or None
        db.session.add(c); db.session.commit()
        flash("Atualizado.", "success"); return redirect(url_for("support_admin.camp_list"))
    return render_template("support/admin/camp_form.html", row=c)

@bp.route("/campaigns/<int:id>/delete", methods=["POST"])
@login_required
def camp_delete(id):
    _guard()
    c = SurveyCampaign.query.get_or_404(id)
    db.session.delete(c); db.session.commit()
    flash("Excluída.", "info"); return redirect(url_for("support/admin.camp_list"))

@bp.route("/campaigns/<int:id>/questions", methods=["GET","POST"])
@login_required
def camp_questions(id):
    _guard()
    c = SurveyCampaign.query.get_or_404(id)
    if request.method == "POST":
        q = SurveyQuestion(
            campaign_id=c.id,
            text=(request.form.get("text") or "").strip(),
            order=int(request.form.get("order") or 0),
            required=bool(request.form.get("required")),
        )
        db.session.add(q); db.session.commit()
        flash("Pergunta adicionada.", "success")
    return render_template("support/admin/questions.html", camp=c)

@bp.route("/questions/<int:id>/delete", methods=["POST"])
@login_required
def question_delete(id):
    _guard()
    q = SurveyQuestion.query.get_or_404(id)
    camp_id = q.campaign_id
    db.session.delete(q); db.session.commit()
    flash("Pergunta excluída.", "info")
    return redirect(url_for("support/admin.camp_questions", id=camp_id))

# Relatório simples
@bp.route("/reports/campaign/<int:id>")
@login_required
def camp_report(id):
    _guard()
    c = SurveyCampaign.query.get_or_404(id)
    # média por pergunta
    agg = []
    for q in c.questions:
        ans = SurveyAnswer.query.join(SurveyResponse).filter(SurveyAnswer.question_id==q.id).all()
        if ans:
            avg = round(sum(a.rating for a in ans)/len(ans), 2)
        else:
            avg = 0
        agg.append({"q": q, "count": len(ans), "avg": avg})
    # últimos comentários
    comments = (SurveyAnswer.query.join(SurveyResponse)
                .filter(SurveyResponse.campaign_id==c.id, SurveyAnswer.comment.isnot(None))
                .order_by(SurveyAnswer.id.desc()).limit(50).all())
    return render_template("support/admin/report.html", camp=c, agg=agg, comments=comments)

# Feedback triagem
@bp.route("/feedback")
@login_required
def fb_list():
    _guard()
    status = request.args.get("status","")
    q = FeedbackMessage.query.order_by(FeedbackMessage.created_at.desc())
    if status in ("novo","lido","resolvido"):
        q = q.filter_by(status=status)
    rows = q.all()
    return render_template("support/admin/feedback_list.html", rows=rows, status=status)

@bp.route("/feedback/<int:id>/set", methods=["POST"])
@login_required
def fb_set_status(id):
    _guard()
    st = request.form.get("status")
    if st not in ("novo","lido","resolvido"):
        flash("Status inválido.", "warning"); return redirect(url_for("support/admin.fb_list"))
    f = FeedbackMessage.query.get_or_404(id)
    f.status = st
    if st == "resolvido":
        f.handled_by = current_user().id
        f.handled_at = datetime.utcnow()
    db.session.add(f); db.session.commit()
    flash("Atualizado.", "success")
    return redirect(url_for("support_admin.fb_list"))
