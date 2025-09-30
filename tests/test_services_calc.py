# tests/test_services_calc.py
def test_calc_service_bootstrap(app):
    # init_motor foi monkeypatchado para criar algo em app.extensions["motor"]
    assert "motor" in app.extensions
