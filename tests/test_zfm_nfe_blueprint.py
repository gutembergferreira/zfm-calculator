# tests/test_zfm_nfe_blueprint.py
import io
import json
import base64
import hashlib
import datetime as dt
import pandas as pd
import pytest
from sqlalchemy import delete

from oraculoicms_app.extensions import db
from oraculoicms_app.models.file import UserFile, NFESummary
from oraculoicms_app.blueprints import nfe as nfe_mod


# ----------------------------
# Utilidades de teste
# ----------------------------

from flask import url_for

@pytest.fixture
def url(app):
    def _u(endpoint, **values):
        # Cria um app/request context só para construir a URL
        with app.test_request_context():
            return url_for(endpoint, **values)
    return _u


def _xml_minimo_ok():
    # XML mínimo com tags ide requeridas
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<NFe xmlns="http://www.portalfiscal.inf.br/nfe">
  <infNFe>
    <ide>
      <cUF>13</cUF>
      <mod>55</mod>
      <serie>1</serie>
      <nNF>123</nNF>
      <cMunFG>1302603</cMunFG>
    </ide>
  </infNFe>
</NFe>"""


def _fake_nfexml_factory(header=None, totais=None, itens=None,
                         transp=None, cobr=None, dups=None, obs=None):
    header = header or {"chave": "FAKE123", "uf_origem": "SP", "uf_destino": "AM"}
    # ✅ use números, não strings:
    totais = totais or {"vNF": 100.0, "vProd": 100.0, "vFrete": 0.0, "vIPI": 0.0, "vOutro": 0.0}
    itens = itens or []
    transp = transp or {}
    cobr = cobr or {}
    dups = dups or []
    obs = obs or ""

    class _Item:
        def __init__(self, nItem=1):
            self.nItem = nItem
            self.cProd = "1"
            self.xProd = "Produto"
            self.ncm = "00000000"
            self.cst = "000"
            self.cfop = "0000"
            self.qCom = 1
            self.vUnCom = 100.0
            self.vProd = 100.0
            self.vFrete = 0.0
            self.vIPI = 0.0
            self.vOutro = 0.0
            self.vICMSDeson = 0.0

    if not itens:
        itens = [_Item(1)]

    class _FakeNFEXML:
        def __init__(self, xml_bytes): self._xml = xml_bytes
        def header(self): return header
        def totais(self): return totais
        def itens(self): return itens
        def transporte(self): return transp
        def cobranca(self): return cobr
        def duplicatas(self): return dups
        def inf_adic(self): return obs

    return _FakeNFEXML



class _CalcResult:
    def __init__(self, icms_st_devido=0.0, memoria=None):
        self.icms_st_devido = icms_st_devido
        self.memoria = memoria or {}


def _fake_get_motor():
    class _Motor:
        def calcula_st(self, item, uf_origem, uf_destino, usar_multiplicador=True):
            # memória mínima com chaves usadas na tela
            mem = {
                "ICMS DESONERADO": 0.0,
                "VALOR DA VENDA COM DESCONTO DE ICMS": 0.0,
                "VALOR DA OPERAÇÃO": 0.0,
                "MARGEM_DE_VALOR_AGREGADO_MVA": 0.0,
                "VALOR AGREGADO": 0.0,
                "BASE ST": 0.0,
                "ALÍQUOTA ICMS-ST": 0.0,
                "icms_teorico_dest": 0.0,
                "icms_origem_calc": 0.0,
                "VALOR_ICMS_ST": 0.0,
                "SALDO_DEVEDOR_ST": 0.0,
                "VALOR SALDO DEVEDOR ICMS ST": 0.0,
                "MULT_SEFAZ": 0.0,
                "VALOR ICMS RETIDO": 0.0,
                "Multiplicador": 0.0,
            }
            return _CalcResult(icms_st_devido=0.0, memoria=mem)
    return _Motor()


# ----------------------------
# Helpers: allowed, _xml_from_request
# ----------------------------
def test_allowed_extensoes():
    assert nfe_mod.allowed("nota.xml") is True
    assert nfe_mod.allowed("NOTA.XML") is True
    assert nfe_mod.allowed("nota.pdf") is False
    assert nfe_mod.allowed("semextensao") is False


def test__xml_from_request_form_file(client, app):
    with app.test_request_context("/nfe/preview", method="POST", data={
        "xml": (io.BytesIO(_xml_minimo_ok()), "nota.xml")
    }, content_type="multipart/form-data"):
        data = nfe_mod._xml_from_request()
        assert data.startswith(b"<?xml")


def test__xml_from_request_form_text(client, app):
    xml_text = _xml_minimo_ok().decode("utf-8")
    with app.test_request_context("/nfe/preview", method="POST", data={
        "xml_text": xml_text
    }):
        data = nfe_mod._xml_from_request()
        assert data.startswith(b"<?xml")


def test__xml_from_request_form_b64(client, app):
    b64 = base64.b64encode(_xml_minimo_ok()).decode("ascii")
    with app.test_request_context("/nfe/preview", method="POST", data={
        "xml_b64": b64
    }):
        data = nfe_mod._xml_from_request()
        assert data.startswith(b"<?xml")


# ----------------------------
# /nfe/preview
# ----------------------------
def test_preview_renderiza(logged_client_user, monkeypatch, url):
    monkeypatch.setattr(nfe_mod, "NFEXML", _fake_nfexml_factory())
    resp = logged_client_user.post(
        url("nfe.preview"),
        data={"xml": (io.BytesIO(_xml_minimo_ok()), "nota.xml")},
        content_type="multipart/form-data"
    )
    assert resp.status_code == 200


def test_preview_sem_xml_redirect(logged_client_user,url):
    resp = logged_client_user.post(
        url("nfe.preview"),
        data={},
        follow_redirects=True
    )
    assert resp.status_code == 200  # redirecionou com flash para core.index


# ----------------------------
# /nfe/calcular
# ----------------------------
def _cria_userfile_cache_para(usuario_id, xml_bytes):
    # cria UserFile com md5 do xml para que a rota encontre o resumo
    md5 = hashlib.md5(xml_bytes).hexdigest()
    uf = UserFile(user_id=usuario_id, filename="nota.xml", storage_path="/tmp/nota.xml",
                  size_bytes=len(xml_bytes), md5=md5, display_name="Nota")
    db.session.add(uf); db.session.commit()
    return uf


def test_calcular_sem_cache_executa_motor(logged_client_user, monkeypatch,url):
    # fakes: NFEXML e motor
    monkeypatch.setattr(nfe_mod, "NFEXML", _fake_nfexml_factory())
    monkeypatch.setattr(nfe_mod, "get_motor", _fake_get_motor)  # <= sem ()

    # sem UserFile/summary => calcula e renderiza
    resp = logged_client_user.post(url("nfe.calcular"), data={
        "xml": (io.BytesIO(_xml_minimo_ok()), "nota.xml")
    }, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Deve conter algo referente a resultado
    assert "resultado" in body.lower() or "icms" in body.lower()


def test_calcular_com_cache_aproveita_calc_json(logged_client_user, monkeypatch,url):
    # Fakes
    FakeNFEXML = _fake_nfexml_factory()
    monkeypatch.setattr(nfe_mod, "NFEXML", FakeNFEXML)
    monkeypatch.setattr(nfe_mod, "get_motor", _fake_get_motor)

    # cria userfile e summary com cache salvo
    with logged_client_user.session_transaction() as sess:
        uid = sess["user"]["id"]

    xml_bytes = _xml_minimo_ok()
    uf = _cria_userfile_cache_para(uid, xml_bytes)

    s = NFESummary(user_file_id=uf.id, chave="FAKE123",
                   calc_json=json.dumps({"linhas":[],"total_st":0.0,"uf_origem":"SP","uf_destino":"AM"}),
                   calc_version=nfe_mod.ALG_VERSION,
                   processed_at=dt.datetime.utcnow())
    db.session.add(s); db.session.commit()

    resp = logged_client_user.post(url("nfe.calcular"), data={
        "xml": (io.BytesIO(xml_bytes), "nota.xml")
    }, content_type="multipart/form-data")
    assert resp.status_code == 200
    # Se usou o cache, a página de resultado vem normalmente
    #assert "resultado" in resp.get_data(as_text=True).lower()


def test_calcular_tenta_indexar_quando_ha_upload(logged_client_user, monkeypatch,url):
    # NFEXML básico
    monkeypatch.setattr(nfe_mod, "NFEXML", _fake_nfexml_factory())
    monkeypatch.setattr(nfe_mod, "get_motor", _fake_get_motor)

    # mock upsert para ser chamado quando houver UserFile com md5
    called = {"ok": False}
    def _fake_upsert(db_, NFEXML_, NFESummary_, UserFile_, uid, xml_bytes, ufid):
        called["ok"] = True
        s = NFESummary(user_file_id=ufid, chave="FAKE123", processed_at=dt.datetime.utcnow())
        db.session.add(s); db.session.commit()
        return s, True

    monkeypatch.setattr(nfe_mod, "upsert_summary_from_xml", _fake_upsert)

    # cria userfile com md5 do xml
    with logged_client_user.session_transaction() as sess:
        uid = sess["user"]["id"]
    xml_bytes = _xml_minimo_ok()
    uf = _cria_userfile_cache_para(uid, xml_bytes)

    resp = logged_client_user.post(url("nfe.calcular"), data={
        "xml": (io.BytesIO(xml_bytes), "nota.xml")
    }, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert called["ok"] is True


# ----------------------------
# /nfe/exportar-pdf
# ----------------------------



def test_exportar_pdf_payload_invalido_redirect(logged_client_user,url):
    resp = logged_client_user.post(url("nfe.exportar_pdf"), data={
        "data": "{invalid json"
    }, follow_redirects=True)
    assert resp.status_code == 200  # redirecionou com flash


# ----------------------------
# Admin: /nfe/admin/run-update e /nfe/admin/reload
# ----------------------------
def test_admin_run_update_executa(logged_client_admin, monkeypatch,url):
    called = {"update": False, "reload": False, "rebuild": False}

    def _fake_run_update_am(): called["update"] = True
    def _fake_reload(): called["reload"] = True
    def _fake_rebuild(): called["rebuild"] = True

    monkeypatch.setattr(nfe_mod, "run_update_am", _fake_run_update_am)
    monkeypatch.setattr(nfe_mod, "reload_matrices", _fake_reload)
    monkeypatch.setattr(nfe_mod, "rebuild_motor", _fake_rebuild)

    resp = logged_client_admin.get(url("nfe.run_update"), follow_redirects=True)
    assert resp.status_code == 200
    assert all(called.values())


def test_admin_reload_executa(logged_client_admin, monkeypatch,url):
    called = {"reload": False, "rebuild": False}
    def _fake_reload(): called["reload"] = True
    def _fake_rebuild(): called["rebuild"] = True
    monkeypatch.setattr(nfe_mod, "reload_matrices", _fake_reload)
    monkeypatch.setattr(nfe_mod, "rebuild_motor", _fake_rebuild)

    resp = logged_client_admin.get(url("nfe.admin_reload"), follow_redirects=True)
    assert resp.status_code == 200
    assert called["reload"] and called["rebuild"]


# ----------------------------
# /nfe/config (GET) e /nfe/config/save (POST)
# ----------------------------
def test_config_view_ok(logged_client_admin, monkeypatch,url):
    df_sources = pd.DataFrame([
        {"ATIVO": "1", "UF": "AM", "NOME": "Fonte X", "URL": "http://x", "TIPO": "csv", "PARSER": "p", "PRIORIDADE": "1"},
        {"ATIVO": "0", "UF": "SP", "NOME": "Fonte Y", "URL": "http://y", "TIPO": "html", "PARSER": "p2", "PRIORIDADE": "2"},
    ])
    df_log = pd.DataFrame([
        {"EXECUTADO_EM": "2024-01-01T00:00:00", "STATUS": "OK", "MENSAGEM": "ok", "LINHAS": 10}
    ])
    monkeypatch.setattr(nfe_mod, "get_matrices", lambda: {"sources": df_sources, "sources_log": df_log})

    resp = logged_client_admin.get(url("nfe.config_view"))
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Banco de dados" in body
    assert "Fonte X" in body
    assert "Última atualização automática" in body


def test_config_tables_view_ok(logged_client_admin, monkeypatch, url):
    df_st = pd.DataFrame([
        {
            "ATIVO": "1",
            "NCM": "12345678",
            "CEST": "1234567",
            "CST_INCLUIR": "10",
            "CST_EXCLUIR": "40",
            "CFOP_INI": "5101",
            "CFOP_FIM": "5102",
            "ST_APLICA": "1",
        }
    ])
    df_log = pd.DataFrame([
        {"EXECUTADO_EM": "2024-01-01T00:00:00", "STATUS": "OK", "MENSAGEM": "ok", "LINHAS": 10}
    ])
    monkeypatch.setattr(nfe_mod, "get_matrices", lambda: {"st_regras": df_st, "sources_log": df_log})

    resp = logged_client_admin.get(url("nfe.config_tables_view"))
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Tabela ST" in body
    assert "Regras de ST" in body


def test_config_save_ok(logged_client_admin, monkeypatch, url, app, db_session):
    with app.app_context():
        db_session.execute(delete(nfe_mod.Source))
        db_session.commit()

    called = {"reload": False, "rebuild": False}
    monkeypatch.setattr(nfe_mod, "reload_matrices", lambda: called.__setitem__("reload", True))
    monkeypatch.setattr(nfe_mod, "rebuild_motor", lambda: called.__setitem__("rebuild", True))

    cols = ["ATIVO","UF","NOME","URL","TIPO","PARSER","PRIORIDADE"]
    form = {
        "cols[]": cols,
        "row_count": "2",
        "row-0-ATIVO": "on",
        "row-0-UF": "AM",
        "row-0-NOME": "Fonte X",
        "row-0-URL": "http://x",
        "row-0-TIPO": "csv",
        "row-0-PARSER": "p",
        "row-0-PRIORIDADE": "1",
        "row-1-ATIVO": "0",
        "row-1-UF": "SP",
        "row-1-NOME": "Fonte Y",
        "row-1-URL": "http://y",
        "row-1-TIPO": "html",
        "row-1-PARSER": "p2",
        "row-1-PRIORIDADE": "2",
    }
    resp = logged_client_admin.post(url("nfe.config_save"), data=form, follow_redirects=True)
    assert resp.status_code == 200
    assert called["reload"] and called["rebuild"]

    with app.app_context():
        rows = nfe_mod.Source.query.order_by(nfe_mod.Source.nome).all()
        assert len(rows) == 2
        data = {row.nome: row for row in rows}
        assert data["Fonte X"].ativo is True
        assert data["Fonte X"].prioridade == 1
        assert data["Fonte Y"].ativo is False
        assert data["Fonte Y"].prioridade == 2


def test_config_tables_save_ok(logged_client_admin, monkeypatch, url, app, db_session):
    with app.app_context():
        db_session.execute(delete(nfe_mod.STRegra))
        db_session.commit()

    called = {"reload": False, "rebuild": False}
    monkeypatch.setattr(nfe_mod, "reload_matrices", lambda: called.__setitem__("reload", True))
    monkeypatch.setattr(nfe_mod, "rebuild_motor", lambda: called.__setitem__("rebuild", True))

    cols = ["ATIVO","NCM","CEST","CST_INCLUIR","CST_EXCLUIR","CFOP_INI","CFOP_FIM","ST_APLICA"]
    form = {
        "cols[]": cols,
        "row_count": "1",
        "row-0-ATIVO": "on",
        "row-0-NCM": "12.34.56.78",
        "row-0-CEST": "12.345.67",
        "row-0-CST_INCLUIR": "10",
        "row-0-CST_EXCLUIR": "",
        "row-0-CFOP_INI": "5101",
        "row-0-CFOP_FIM": "5102",
        "row-0-ST_APLICA": "Sim",
    }

    resp = logged_client_admin.post(url("nfe.config_tables_save"), data=form, follow_redirects=True)
    assert resp.status_code == 200
    assert called["reload"] and called["rebuild"]

    with app.app_context():
        rows = nfe_mod.STRegra.query.order_by(nfe_mod.STRegra.ncm).all()
        assert len(rows) == 1
        regra = rows[0]
        assert regra.ncm == "12345678"
        assert regra.cest == "1234567"
        assert regra.cst_incluir == "10"
        assert regra.cfop_ini == "5101"
        assert regra.cfop_fim == "5102"
        assert regra.st_aplica is True


# ----------------------------
# /nfe/debug/sheets
# ----------------------------
def test_debug_sheets_ok(client, monkeypatch,url):
    df_sources = pd.DataFrame([
        {"ATIVO": "1", "UF": "AM", "NOME": "Fonte"}
    ])
    df_logs = pd.DataFrame([
        {"EXECUTADO_EM": "2024-01-01T00:00:00", "STATUS": "OK"}
    ])
    monkeypatch.setattr(nfe_mod, "get_matrices", lambda: {"sources": df_sources, "sources_log": df_logs})

    r = client.get(url("nfe.debug_sheets"))
    assert r.status_code == 200
    data = r.get_json()
    assert data["sources_rows"] == 1
    assert data["log_entries"] == 1
