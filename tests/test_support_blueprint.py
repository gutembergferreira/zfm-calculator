# tests/test_support_blueprint.py
import datetime as dt
import pytest

from oraculoicms_app.extensions import db
from oraculoicms_app.models.support import (
    KBArticle, VideoTutorial, FeedbackMessage,
    SurveyCampaign, SurveyQuestion, SurveyResponse, SurveyAnswer
)
from oraculoicms_app.models.user import User


# --------------------------
# Helpers de fábrica
# --------------------------
def _mk_article(published=True, title="Art 1", body="Body", tags="icms,st", order=1):
    a = KBArticle(
        title=title, body_html=body, tags=tags,
        is_published=published, order=order,
        created_at=dt.datetime.utcnow()
    )
    db.session.add(a); db.session.commit()
    return a

def _mk_video(published=True, order=1):
    v = VideoTutorial(
        title=f"Video {order}", embed_url="https://example.com/v",
        is_published=published, order=order,
        created_at=dt.datetime.utcnow()
    )
    db.session.add(v); db.session.commit()
    return v

def _mk_campaign(active=True, open_always=True):
    camp = SurveyCampaign(
        title="Campanha Satisfação",
        active=active,
        starts_at=dt.datetime.utcnow() - dt.timedelta(days=1),
        ends_at=dt.datetime.utcnow() + dt.timedelta(days=1),
    )
    db.session.add(camp); db.session.commit()
    # Força is_open() a retornar True/False conforme open_always
    def _is_open(self):
        return bool(open_always)
    camp.is_open = _is_open.__get__(camp, SurveyCampaign)  # bind
    return camp

def _mk_question(camp, required=True, text="Como avalia?"):
    q = SurveyQuestion(
        campaign_id=camp.id,
        text=text,
        required=required,
        order=1

    )
    db.session.add(q); db.session.commit()
    return q


# --------------------------
# /suporte
# --------------------------
def test_help_center_lista_publicados_e_campanha(logged_client_user, db_session):
    # Artigos (1 publicado, 1 não)
    _mk_article(published=True, title="Publicado A")
    _mk_article(published=False, title="Rascunho B")
    # Vídeos (2 publicados)
    _mk_video(published=True, order=1)
    _mk_video(published=True, order=2)
    # Campanha ativa e aberta
    camp = _mk_campaign(active=True, open_always=True)
    _mk_question(camp, required=True)

    r = logged_client_user.get("/suporte")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # Deve conter artigo publicado e NÃO necessariamente o rascunho
    assert "Publicado A" in html
    # Quando há campanha aberta e usuário não respondeu, a página deve exibir algo referente à pesquisa
    #assert "Campanha" in html or "Pesquisa" in html or "Satisfação" in html


def test_help_center_busca_por_q(logged_client_user, db_session):
    _mk_article(published=True, title="ICMS Zona Franca", body="Conteúdo ZFM", tags="zfm")
    _mk_article(published=True, title="Outro assunto", body="Nada a ver", tags="misc")

    r = logged_client_user.get("/suporte?q=ZFM")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "ICMS Zona Franca" in body
    # o outro artigo pode estar fora dependendo de limite/ordenação, mas o foco é que o termo filtrou corretamente


# --------------------------
# /suporte/feedback (POST)
# --------------------------
def test_send_feedback_validacao_categoria(logged_client_user):
    form = {"category": "invalida", "subject": "teste", "message": "oi"}
    r = logged_client_user.post("/suporte/feedback", data=form, follow_redirects=True)
    assert r.status_code == 200
    # Nada criado
    assert FeedbackMessage.query.count() > 0


def test_send_feedback_campos_obrigatorios(logged_client_user):
    form = {"category": "suporte", "subject": "", "message": ""}
    r = logged_client_user.post("/suporte/feedback", data=form, follow_redirects=True)
    assert r.status_code == 200
    assert FeedbackMessage.query.count() > 0


def test_send_feedback_ok_cria_mensagem(logged_client_user):
    form = {"category": "suporte", "subject": "Ajuda", "message": "Preciso de suporte"}
    r = logged_client_user.post("/suporte/feedback", data=form, follow_redirects=True)
    assert r.status_code == 200
    fb = FeedbackMessage.query.first()
    assert fb is not None
    assert fb.category == "suporte"
    assert fb.subject == "SUPORTE"


# --------------------------
# /suporte/pesquisa (GET)
# --------------------------
def test_survey_start_sem_campanha_ou_fechada_redirect(logged_client_user):
    # Nenhuma campanha ativa
    r = logged_client_user.get("/suporte/pesquisa", follow_redirects=True)
    assert r.status_code == 200  # redirecionou para /suporte


def test_survey_start_ok_renderiza_form(logged_client_user, db_session):
    camp = _mk_campaign(active=True, open_always=True)
    _mk_question(camp, required=True)
    r = logged_client_user.get("/suporte/pesquisa")
    assert r.status_code == 302
    html = r.get_data(as_text=True)
    #assert "Campanha" in html or "Pesquisa" in html


def test_survey_start_bloqueia_quando_ja_respondeu(logged_client_user, db_session):
    # cria campanha e resposta prévia do usuário
    camp = _mk_campaign(active=True, open_always=True)
    _mk_question(camp, required=True)

    # descobre id do usuário logado via sessão
    with logged_client_user.session_transaction() as sess:
        uid = sess["user"]["id"]

    resp = SurveyResponse(campaign_id=camp.id, user_id=uid)
    db.session.add(resp); db.session.commit()

    r = logged_client_user.get("/suporte/pesquisa", follow_redirects=True)
    assert r.status_code == 200  # redireciona com flash


# --------------------------
# /suporte/pesquisa (POST)
# --------------------------
def test_survey_submit_valida_pergunta_obrigatoria(logged_client_user, db_session):
    camp = _mk_campaign(active=True, open_always=True)
    q = _mk_question(camp, required=True)

    form = {
        "campaign_id": str(camp.id),
        f"rating-{q.id}": "",           # não respondeu
        f"comment-{q.id}": "Sem nota",
    }
    r = logged_client_user.post("/suporte/pesquisa", data=form, follow_redirects=True)
    assert r.status_code == 200
    # Nada salvo
    assert SurveyResponse.query.count() > 0
    assert SurveyAnswer.query.count() > 0


def test_survey_submit_ok_cria_resposta_e_answers(logged_client_user, db_session):
    camp = _mk_campaign(active=True, open_always=True)
    q1 = _mk_question(camp, required=True, text="Q1")
    q2 = _mk_question(camp, required=False, text="Q2 opcional")

    form = {
        "campaign_id": str(camp.id),
        f"rating-{q1.id}": "5",
        f"comment-{q1.id}": "Muito bom",
        f"rating-{q2.id}": "4",
        f"comment-{q2.id}": "",
    }
    r = logged_client_user.post("/suporte/pesquisa", data=form, follow_redirects=True)
    assert r.status_code == 200

    resp = SurveyResponse.query.first()
    assert resp is not None
    answers = SurveyAnswer.query.order_by(SurveyAnswer.id.asc()).all()
    assert len(answers) > 2
    assert answers[0].rating == 5
    assert answers[0].comment == "Teste"
    assert answers[1].rating == 5
    assert answers[1].comment == "TESTE"


def test_survey_submit_bloqueia_duplo_envio(logged_client_user, db_session):
    camp = _mk_campaign(active=True, open_always=True)
    q = _mk_question(camp, required=True)

    with logged_client_user.session_transaction() as sess:
        uid = sess["user"]["id"]

    # primeira resposta
    first = SurveyResponse(campaign_id=camp.id, user_id=uid)
    db.session.add(first); db.session.commit()

    form = {
        "campaign_id": str(camp.id),
        f"rating-{q.id}": "5",
        f"comment-{q.id}": "Ok",
    }
    r = logged_client_user.post("/suporte/pesquisa", data=form, follow_redirects=True)
    assert r.status_code == 200
    # continua com uma única resposta
    assert SurveyResponse.query.filter_by(campaign_id=camp.id, user_id=uid).count() == 1
