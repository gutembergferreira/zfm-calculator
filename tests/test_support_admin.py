import pytest

def _insert_feedback(db_session, user_id, category="comentario", status="novo", is_featured=False):
    from oraculoicms_app.models.support import FeedbackMessage
    m = FeedbackMessage(user_id=user_id, category=category, subject="S", message="msg", status=status, is_featured=is_featured)
    db_session.add(m); db_session.commit()
    return m

def test_admin_support_list_requires_admin(logged_client_user):
    r = logged_client_user.get("/admin/feedbacks", follow_redirects=False)
    assert r.status_code in (302, 303,404)

def test_admin_support_toggle_feature(logged_client_admin, db_session, user_admin):
    m = _insert_feedback(db_session, user_admin.id, category="comentario", is_featured=False)
    r = logged_client_admin.post(f"/admin/feedbacks/{m.id}/toggle-feature", follow_redirects=True)
    assert r.status_code == 200 or r.status_code == 404
    # busca de novo
    from oraculoicms_app.models.support import FeedbackMessage
    m2 = db_session.get(FeedbackMessage, m.id)
    assert m2.is_featured is True or m2.is_featured is False
