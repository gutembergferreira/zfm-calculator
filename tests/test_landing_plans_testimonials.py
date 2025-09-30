def test_landing_shows_plans_and_testimonials(client, db_session, plan_basic, user_admin):
    # cria +1 plano
    from oraculoicms_app.models.plan import Plan
    #db_session.add(Plan(slug="pro", name="Pro", price_month_cents=14900, active=True)); db_session.commit()
    # cria 1 depoimento destacado
    from oraculoicms_app.models.support import FeedbackMessage
    db_session.add(FeedbackMessage(user_id=user_admin.id, category="comentario", subject="Ok", message="Muito bom", status="lido", is_featured=True))
    db_session.commit()

    r = client.get("/")
    html = r.get_data(as_text=True)
    assert "Básico" in html and "Pro" in html
    assert "Muito bom" in html
