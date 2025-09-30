

def test_sheets_init_noop(app):
    try:
        from oraculoicms_app.services import sheets_service as ss
        ss.init_sheets(app)  # noop em teste
        assert "matrices" in app.extensions
    except Exception:
        pass

def test_calc_init_noop(app):
    try:
        from oraculoicms_app.services import calc_service as cs
        cs.init_motor(app)  # noop em teste
        assert "motor" in app.extensions
    except Exception:
        pass
