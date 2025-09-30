# oraculoicms_app/models/support.py
from __future__ import annotations
from datetime import datetime
from ..extensions import db

class KBArticle(db.Model):
    __tablename__ = "kb_articles"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body_html = db.Column(db.Text, nullable=False)            # guarda HTML “simples” (ou markdown renderizado)
    tags = db.Column(db.String(200), default="")              # ex.: "importacao,xml"
    is_published = db.Column(db.Boolean, default=True, index=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class VideoTutorial(db.Model):
    __tablename__ = "video_tutorials"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    # use embed do YouTube/Vimeo (ex.: https://www.youtube.com/embed/XXXXXXXX)
    embed_url = db.Column(db.String(500), nullable=False)
    is_published = db.Column(db.Boolean, default=True, index=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class FeedbackMessage(db.Model):
    __tablename__ = "feedback_messages"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    category = db.Column(db.String(30), nullable=False)   # "sugestao" | "erro" | "comentario" | "suporte"
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="novo", index=True)  # "novo" | "lido" | "resolvido"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    handled_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    handled_at = db.Column(db.DateTime, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    is_featured = db.Column(db.Boolean, nullable=False, default=False)

class SurveyCampaign(db.Model):
    __tablename__ = "survey_campaigns"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    active = db.Column(db.Boolean, default=False, index=True)
    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_open(self):
        now = datetime.utcnow()
        if self.starts_at and now < self.starts_at: return False
        if self.ends_at and now > self.ends_at: return False
        return bool(self.active)

class SurveyQuestion(db.Model):
    __tablename__ = "survey_questions"
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("survey_campaigns.id"), nullable=False, index=True)
    text = db.Column(db.String(500), nullable=False)
    order = db.Column(db.Integer, default=0)
    required = db.Column(db.Boolean, default=True)
    campaign = db.relationship("SurveyCampaign", backref=db.backref("questions", cascade="all,delete-orphan", order_by="SurveyQuestion.order"))

class SurveyResponse(db.Model):
    __tablename__ = "survey_responses"
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("survey_campaigns.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    campaign = db.relationship("SurveyCampaign")
    # unique: um envio por usuário por campanha
    __table_args__ = (db.UniqueConstraint("campaign_id", "user_id", name="uq_campaign_user"),)

class SurveyAnswer(db.Model):
    __tablename__ = "survey_answers"
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey("survey_responses.id"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("survey_questions.id"), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)  # 1..5
    comment = db.Column(db.Text, nullable=True)
    response = db.relationship("SurveyResponse", backref=db.backref("answers", cascade="all,delete-orphan"))
    question = db.relationship("SurveyQuestion")
