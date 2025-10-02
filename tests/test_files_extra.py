# tests/test_files_blueprint.py
from __future__ import annotations
import io
import json
from pathlib import Path
from datetime import datetime, timedelta

import pytest

from oraculoicms_app.models import User
from oraculoicms_app.models.file import UserFile, NFESummary, AuditLog
from oraculoicms_app.models.user_quota import UserQuota


# --- Helpers -----------------------------------------------------------------

def make_minimal_nfe_xml(chave="NFe123", uf="35", nNF="1", serie="1"):
    # Gera um nfeProc válido para _is_nfe_xml (com nós ide/cUF/nNF/serie)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">
  <NFe>
    <infNFe Id="{chave}">
      <ide>
        <cUF>{uf}</cUF>
        <nNF>{nNF}</nNF>
        <serie>{serie}</serie>
        <mod>55</mod>
        <cMunFG>3550308</cMunFG>
      </ide>
      <emit>
        <CNPJ>11111111000191</CNPJ>
        <xNome>EMITENTE LTDA</xNome>
        <enderEmit>
          <xLgr>Rua A</xLgr><nro>100</nro><xBairro>Centro</xBairro><xMun>Sao Paulo</xMun><UF>SP</UF><CEP>01000-000</CEP>
        </enderEmit>
      </emit>
      <dest>
        <CNPJ>22222222000172</CNPJ>
        <xNome>DEST LTDA</xNome>
        <enderDest>
          <xLgr>Av B</xLgr><nro>200</nro><xBairro>Centro</xBairro><xMun>Manaus</xMun><UF>AM</UF><CEP>69000-000</CEP>
        </enderDest>
      </dest>
      <det nItem="1">
        <prod>
          <cProd>001</cProd><xProd>Produto 1</xProd>
          <NCM>01012100</NCM><CFOP>6101</CFOP>
          <uCom>UN</uCom><uTrib>UN</uTrib>
          <qCom>2.0000</qCom><vUnCom>10.00</vUnCom>
          <vFrete>0.00</vFrete>
        </prod>
        <imposto>
          <ICMS><ICMS00><CST>00</CST></ICMS00></ICMS>
          <IPI><IPITrib><vIPI>0.00</vIPI></IPITrib></IPI>
        </imposto>
      </det>
      <total>
        <ICMSTot>
          <vProd>20.00</vProd><vFrete>0.00</vFrete><vIPI>0.00</vIPI>
          <vDesc>0.00</vDesc><vOutro>0.00</vOutro><vICMSDeson>0.00</vICMSDeson>
          <vICMS>0.00</vICMS><vST>0.00</vST><vNF>20.00</vNF>
        </ICMSTot>
      </total>
    </infNFe>
  </NFe>
</nfeProc>
""".encode("utf-8")


@pytest.fixture(autouse=True)
def _tmp_upload_folder(app, tmp_path, monkeypatch):
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    yield
    # cleanup é automático pelo tmp_path


# --- Unit tests para helpers internos ----------------------------------------

def test__is_nfe_xml_variants():
    from oraculoicms_app.blueprints import files as mod

    good = make_minimal_nfe_xml()
    ok, err = mod._is_nfe_xml(good)
    assert ok is True and err == ""

    bad_not_xml = b"not-xml"
    ok2, _ = mod._is_nfe_xml(bad_not_xml)
    assert ok2 is False

    # root inválido
    bad_root = b"<xml></xml>"
    ok3, _ = mod._is_nfe_xml(bad_root)
    assert ok3 is False


# --- Fluxo de upload/list/preview/download -----------------------------------

def _do_upload(client, xml_bytes, filename="nota.xml"):
    data = {"xml": (io.BytesIO(xml_bytes), filename), "display_name": "Minha NF"}
    r = client.post("/upload-xml", data=data, content_type="multipart/form-data", follow_redirects=False)
    return r


def test_upload_list_and_ver_xml(logged_client_user, db_session):
    # upload ok
    r = _do_upload(logged_client_user, make_minimal_nfe_xml())
    assert r.status_code in (302, 303)

    uf = db_session.query(UserFile).first()
    assert uf is not None
    assert Path(uf.storage_path).is_file()

    # list
    r2 = logged_client_user.get("/meus-arquivos")
    assert r2.status_code == 200
    html = r2.get_data(as_text=True)
    # A página pode mostrar display_name no lugar do filename
    assert ("Minha NF" in html) or (uf.filename in html)


# --- parse_xml: mock NFEXML + upsert + motor ---------------------------------

class _FakeMotorResult:
    def __init__(self):
        self.icms_st_devido = 7.5
        self.memoria = {
            "VALOR DA VENDA COM DESCONTO DE ICMS": 19.0,
            "VALOR DA OPERAÇÃO": 19.0,
            "MARGEM_DE_VALOR_AGREGADO_MVA": 40.0,
            "BASE_ST": 25.0,
            "ALÍQUOTA ICMS-ST": 18.0,
            "VALOR_ICMS_ST": 7.5,
            "SALDO_DEVEDOR_ST": 7.5,
        }


class _FakeMotor:
    def calcula_st(self, item, uf_origem, uf_destino, usar_multiplicador=True):
        return _FakeMotorResult()


class _FakeNFEXML:
    def __init__(self, xml_bytes):
        self._xml = xml_bytes
    def header(self):
        return {"chave": "CHAVE_X", "uf_origem": "SP", "uf_destino": "AM"}
    def totais(self):
        return {"vNF": "20.00", "vProd": "20.00"}
    def itens(self):
        class _Item:
            nItem="1"; cProd="001"; xProd="Produto 1"; ncm="0101"; cst="00"; cfop="6101"
            from decimal import Decimal
            qCom=Decimal("2"); vUnCom=Decimal("10"); vProd=Decimal("20")
            vFrete=Decimal("0"); vIPI=Decimal("0"); vOutro=Decimal("0"); vICMSDeson=Decimal("0")
            uCom="UN"; uTrib="UN"; cEAN=""; cEANTrib=""; cest=""
        return [_Item()]






