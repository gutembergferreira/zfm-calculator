# tests/test_extensions_cli.py
def test_init_db_cli_runs(app, monkeypatch):
    runner = app.test_cli_runner()
    res = runner.invoke(args=["init-db"])
    assert res.exit_code == 0
    assert "Tabelas criadas" in res.output or res.output == ""
