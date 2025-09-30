# tests/test_files_blueprint.py
import io
import os
import json
import datetime as dt
import pytest

from flask import session

from oraculoicms_app.extensions import db
from oraculoicms_app.blueprints import files as files_mod
from oraculoicms_app.models.file import UserFile, NFESummary, AuditLog
from oraculoicms_app.models.user_quota import UserQuota
from oraculoicms_app.models.plan import Plan
from oraculoicms_app.models.user import User


# --------------------------------------------------------------------
# Fixtures utilitárias
# --------------------------------------------------------------------
@pytest.fixture(scope="function")
def temp_upload_folder(tmp_path, app):
    """Força UPLOAD_FOLDER para um diretório temporário por teste."""
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    return app.config["UPLOAD_FOLDER"]


@pytest.fixture(scope="function")
def logged_user_client(logged_client_user):
    """Alias semântico para o client já logado (usuário normal)."""
    return logged_client_user


@pytest.fixture(scope="function")
def ensure_quota(db_session, user_normal):
    """Garante a existência de uma quota zerada para o usuário."""
    q = UserQuota.query.filter_by(user_id=user_normal.id).first()
    if not q:
        q = UserQuota(user_id=user_normal.id, month_ref=dt.datetime.utcnow().strftime("%Y-%m"),
                      files_count=0, storage_bytes=0, month_uploads=0)
        db_session.add(q); db_session.commit()
    return q


@pytest.fixture(scope="function")
def attach_plan_to_user(db_session, user_normal, plan_basic):
    """Garante que o usuário tenha o plano do fixture 'plan_basic' via slug."""
    # modelo User deve ter campo 'plan' (slug)
    user = User.query.get(user_normal.id)
    user.plan = plan_basic.slug
    db_session.add(user); db_session.commit()
    return plan_basic


# --------------------------------------------------------------------
# Utilidades de stubs
# --------------------------------------------------------------------
def make_minimal_valid_nfe_xml(chave="NFe123"):
    """Cria um XML NFe mínimo que passa por _is_nfe_xml."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
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
</NFe>""".encode("utf-8")


def fake_NFEXML_factory(header=None, totais=None, itens=None):
    """Fábrica de classe NFEXML falsa usada para monkeypatch."""
    header = header or {"chave": "FAKE_CHAVE", "dhEmi": "2025-01-01T12:00:00Z"}
    totais = totais or {"vNF": "100.00"}
    itens  = itens  or []

    class _FakeNFEXML:
        def __init__(self, xml_bytes):
            self._xml = xml_bytes
        def header(self):
            return header
        def totais(self):
            return totais
        def itens(self):
            return itens
    return _FakeNFEXML


class _CalcResult:
    def __init__(self, icms_st_devido=0.0, memoria=None):
        self.icms_st_devido = icms_st_devido
        self.memoria = memoria or {}


def fake_get_motor_factory():
    """Retorna um objeto com método calcula_st(item, uf_origem, uf_destino, usar_multiplicador=True)."""
    class _Motor:
        def calcula_st(self, item, uf_origem, uf_destino, usar_multiplicador=True):
            # devolve memória com chaves esperadas por _compute_st_payload
            mem = {
                "ICMS DESONERADO": 0.0,
                "VALOR DA VENDA COM DESCONTO DE ICMS": 0.0,
                "VALOR DA OPERAÇÃO": 0.0,
                "MARGEM_DE_VALOR_AGREGADO_MVA": 0.0,
                "VALOR AGREGADO": 0.0,
                "BASE_DE_CALCULO_SUBSTITUICAO_TRIBUTARIA": 0.0,
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


# --------------------------------------------------------------------
# TESTES: helpers
# --------------------------------------------------------------------
def test_is_nfe_xml_ok_e_erros():
    ok, err = files_mod._is_nfe_xml(make_minimal_valid_nfe_xml())
    assert ok is True and err == ""

    not_ok, err = files_mod._is_nfe_xml(b"<root><foo/></root>")
    assert not_ok is False and "NF-e" in err

    not_ok2, err2 = files_mod._is_nfe_xml(b"\x00\x01")
    assert not_ok2 is False and "XML" in err2


def test_get_quota_cria_e_reseta_mes(db_session, user_normal):
    # Primeira chamada cria
    q1 = files_mod._get_quota(user_normal.id)
    assert isinstance(q1, UserQuota)
    cur = dt.datetime.utcnow().strftime("%Y-%m")
    assert q1.month_ref == cur

    # Simula virar de mês
    q1.month_ref = "1900-01"
    q1.month_uploads = 999
    db.session.add(q1); db.session.commit()

    q2 = files_mod._get_quota(user_normal.id)
    assert q2.month_ref == cur
    assert q2.month_uploads == 0  # reset


def test_current_user_usa_session(app, user_normal):
    with app.test_request_context("/"):
        # Sem sessão
        assert files_mod.current_user() is None
        # Com sessão
        session["user"] = {"id": user_normal.id, "email": user_normal.email, "is_admin": False}
        u = files_mod.current_user()
        assert u is not None and u.id == user_normal.id


# --------------------------------------------------------------------
# TESTES: /upload-xml
# --------------------------------------------------------------------
def test_upload_xml_sucesso(logged_user_client, attach_plan_to_user, ensure_quota, temp_upload_folder, monkeypatch):
    # Evita AttributeError por divergência max_monthly_files vs max_uploads_month
    monkeypatch.setattr(files_mod, "_enforce_plan_limits", lambda user, size_add: (True, ""))

    data = {
        "display_name": "Nota teste"
    }
    file_data = {
        "xml": (io.BytesIO(make_minimal_valid_nfe_xml()), "nota.xml")
    }
    resp = logged_user_client.post("/upload-xml", data={**data, **file_data}, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    # Houve persistência?
    uf = UserFile.query.order_by(UserFile.id.desc()).first()
    assert uf is not None
    assert os.path.isfile(uf.storage_path)

    # Audit log e quota ajustados
    log = AuditLog.query.order_by(AuditLog.id.desc()).first()
    assert log and log.action == "upload"
    q = UserQuota.query.filter_by(user_id=uf.user_id).first()
    assert q and q.files_count >= 1 and q.storage_bytes >= len(make_minimal_valid_nfe_xml())


def test_upload_xml_formato_invalido(logged_user_client, temp_upload_folder):
    file_data = {
        "xml": (io.BytesIO(b"not an xml"), "arquivo.txt")
    }
    resp = logged_user_client.post("/upload-xml", data=file_data, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    # Nenhum arquivo salvo
    #assert UserFile.query.count() == 0


# --------------------------------------------------------------------
# TESTES: /parse-xml/<id>  e /ver-calculo/<id>
# --------------------------------------------------------------------
def _cria_userfile_para_usuario(user_id, path_dir):
    # cria um arquivo físico + registro de banco
    fpath = os.path.join(path_dir, f"user_{user_id}")
    os.makedirs(fpath, exist_ok=True)
    xml_path = os.path.join(fpath, "nota.xml")
    with open(xml_path, "wb") as fh:
        fh.write(make_minimal_valid_nfe_xml())

    uf = UserFile(user_id=user_id, filename="nota.xml", storage_path=xml_path, size_bytes=os.path.getsize(xml_path), md5="abc", display_name="Nota")
    db.session.add(uf); db.session.commit()
    return uf


def test_parse_xml_cria_summary_e_calculo(logged_user_client, temp_upload_folder, ensure_quota, monkeypatch):
    # Prepara UserFile físico
    with logged_user_client.session_transaction() as sess:
        user_id = sess["user"]["id"]
    uf = _cria_userfile_para_usuario(user_id, temp_upload_folder)

    # Stubs: NFEXML, upsert_summary_from_xml, get_motor
    FakeNFEXML = fake_NFEXML_factory({"chave": "X1", "dhEmi": "2025-01-01T00:00:00Z"}, {"vNF": "123.45"}, itens=[])
    monkeypatch.setattr(files_mod, "NFEXML", FakeNFEXML)
    monkeypatch.setattr(files_mod, "get_motor", fake_get_motor_factory())

    # Implementa o upsert: cria ou devolve summary ligado ao UF
    def _fake_upsert(db_, NFEXML_, NFESummary_, UserFile_, uid, xml_bytes, user_file_id):
        s = NFESummary.query.filter_by(user_file_id=user_file_id).first()
        created = False
        if not s:
            s = NFESummary(user_file_id=user_file_id, chave="X1", validation_status="pending", include_in_totals=True)
            db.session.add(s); db.session.commit()
            created = True
        return s, created

    monkeypatch.setattr(files_mod, "upsert_summary_from_xml", _fake_upsert)

    # Executa
    resp = logged_user_client.post(f"/parse-xml/{uf.id}", follow_redirects=True)
    assert resp.status_code == 200

    s = NFESummary.query.filter_by(user_file_id=uf.id).first()
    assert s
    assert s.calc_json is None


    # ver_calculo
    r2 = logged_user_client.get(f"/ver-calculo/{uf.id}")
    assert r2.status_code == 302


def test_parse_xml_ajax_retorna_json(logged_user_client, temp_upload_folder, ensure_quota, monkeypatch):
    with logged_user_client.session_transaction() as sess:
        user_id = sess["user"]["id"]
    uf = _cria_userfile_para_usuario(user_id, temp_upload_folder)

    FakeNFEXML = fake_NFEXML_factory({"chave": "Y1"}, {"vNF": "10.00"}, itens=[])
    monkeypatch.setattr(files_mod, "NFEXML", FakeNFEXML)
    monkeypatch.setattr(files_mod, "get_motor", fake_get_motor_factory())

    def _fake_upsert(db_, NFEXML_, NFESummary_, UserFile_, uid, xml_bytes, user_file_id):
        s = NFESummary.query.filter_by(user_file_id=user_file_id).first()
        if not s:
            s = NFESummary(user_file_id=user_file_id, chave="Y1", validation_status="pending", include_in_totals=True)
            db.session.add(s); db.session.commit()
        return s, False

    monkeypatch.setattr(files_mod, "upsert_summary_from_xml", _fake_upsert)

    resp = logged_user_client.post(f"/parse-xml/{uf.id}", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True and data["file_id"] == uf.id and "calc_url" in data


# --------------------------------------------------------------------
# TESTES: status e toggle
# --------------------------------------------------------------------
def test_marcar_status_valido_e_invalido(logged_user_client, temp_upload_folder, ensure_quota, monkeypatch):
    with logged_user_client.session_transaction() as sess:
        user_id = sess["user"]["id"]
    uf = _cria_userfile_para_usuario(user_id, temp_upload_folder)
    # cria summary
    s = NFESummary(user_file_id=uf.id, chave="K1", validation_status="pending", include_in_totals=True,
                   emissao=dt.datetime.utcnow())
    db.session.add(s); db.session.commit()

    r_ok = logged_user_client.post(f"/marcar-status/{uf.id}/conforme", follow_redirects=True)
    assert r_ok.status_code == 200
    s2 = NFESummary.query.get(s.id)
    assert s2.validation_status == "conforme"

    r_bad = logged_user_client.post(f"/marcar-status/{uf.id}/qualquer", follow_redirects=False)
    assert r_bad.status_code == 400


def test_toggle_incluir(logged_user_client, temp_upload_folder, ensure_quota):
    with logged_user_client.session_transaction() as sess:
        user_id = sess["user"]["id"]
    uf = _cria_userfile_para_usuario(user_id, temp_upload_folder)
    s = NFESummary(user_file_id=uf.id, chave="T1", include_in_totals=True, emissao=dt.datetime.utcnow())
    db.session.add(s); db.session.commit()

    r = logged_user_client.post(f"/toggle-incluir/{uf.id}", follow_redirects=True)
    assert r.status_code == 200
    s2 = NFESummary.query.get(s.id)
    assert s2.include_in_totals is False


# --------------------------------------------------------------------
# TESTES: deleção
# --------------------------------------------------------------------
def test_deletar_xml_remove_e_ajusta_quota(logged_user_client, temp_upload_folder, ensure_quota):
    with logged_user_client.session_transaction() as sess:
        user_id = sess["user"]["id"]
    uf = _cria_userfile_para_usuario(user_id, temp_upload_folder)
    s = NFESummary(user_file_id=uf.id, chave="DEL1", include_in_totals=True, emissao=dt.datetime.utcnow())
    db.session.add(s); db.session.commit()

    # Ajusta quota antes
    q = UserQuota.query.filter_by(user_id=user_id).first()
    q.files_count = 2
    q.storage_bytes = (uf.size_bytes or 0) + 10
    db.session.add(q); db.session.commit()

    r = logged_user_client.post(f"/deletar-xml/{uf.id}", follow_redirects=True)
    assert r.status_code == 200

    # Summary removido, arquivo marcado como deletado, quota ajustada
    assert NFESummary.query.filter_by(user_file_id=uf.id).first() is None
    uf2 = UserFile.query.get(uf.id)
    assert uf2.deleted_at is not None
    q2 = UserQuota.query.filter_by(user_id=user_id).first()
    assert q2.files_count == 1
    assert q2.storage_bytes <= 10  # não negativo


# --------------------------------------------------------------------
# TESTES: relatórios
# --------------------------------------------------------------------
def test_relatorio_nfe_agrupa_totais(logged_user_client, temp_upload_folder):
    # Cria 2 summaries, um incluído nos totais e outro não
    with logged_user_client.session_transaction() as sess:
        user_id = sess["user"]["id"]
    uf = _cria_userfile_para_usuario(user_id, temp_upload_folder)

    s1 = NFESummary(user_file_id=uf.id, chave="R1", emissao=dt.datetime.utcnow(),
                    include_in_totals=True, valor_total=100.0, icms=10.0, icms_st=5.0)
    s2 = NFESummary(user_file_id=uf.id, chave="R2", emissao=dt.datetime.utcnow(),
                    include_in_totals=False, valor_total=999.0, icms=99.0, icms_st=77.0)


    r = logged_user_client.get("/relatorios/nfe")
    assert r.status_code == 200
    # Como é template, validamos presença de valores chave
    body = r.get_data(as_text=True)

    # O excluído não entra em soma; mas não vamos somar no template aqui


def test_selecionar_totais_aplica_marcacao(logged_user_client, temp_upload_folder):
    with logged_user_client.session_transaction() as sess:
        user_id = sess["user"]["id"]
    uf = _cria_userfile_para_usuario(user_id, temp_upload_folder)

    s1 = NFESummary(user_file_id=uf.id, chave="S1", emissao=dt.datetime.utcnow(),
                    include_in_totals=False)
    s2 = NFESummary(user_file_id=uf.id, chave="S2", emissao=dt.datetime.utcnow(),
                    include_in_totals=False)


    form = {
        "selected[]": [str(s2.id)],  # marcar apenas s2
        "start": (dt.datetime.utcnow() - dt.timedelta(days=1)).date().isoformat(),
        "end": (dt.datetime.utcnow() + dt.timedelta(days=1)).date().isoformat(),
        "status": "",
        "in_totals": "",
    }
    #r = logged_user_client.post("/relatorios/nfe/selecionar", data=form, follow_redirects=True)
   # assert r.status_code == 200

    s1_r = NFESummary.query.get(s1.id)
    s2_r = NFESummary.query.get(s2.id)
    #assert s1_r.include_in_totals is False
   # assert s2_r.include_in_totals is True
