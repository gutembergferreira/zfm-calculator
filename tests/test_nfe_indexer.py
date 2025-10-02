# tests/test_nfe_indexer.py
import json
import datetime as dt
import pytest

from oraculoicms_app.extensions import db
from oraculoicms_app.blueprints.nfe_indexer import _parse_emissao_iso, upsert_summary_from_xml


# -------------------------------------------------------------------
# Modelos de TESTE (independentes dos modelos da aplicação)
# -------------------------------------------------------------------
def define_test_models():
    class TestUserFile(db.Model):
        __tablename__ = "test_user_files"
        __table_args__ = {"extend_existing": True}  # <= evita o erro de redefinição
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, nullable=False)

    class TestNFESummary(db.Model):
        __tablename__ = "test_nfe_summaries"
        __table_args__ = {"extend_existing": True}  # <= evita o erro de redefinição
        id = db.Column(db.Integer, primary_key=True)
        user_file_id = db.Column(db.Integer, db.ForeignKey("test_user_files.id"), nullable=False)
        chave = db.Column(db.String(64), index=True, nullable=False)

        emissao = db.Column(db.DateTime)
        emit_cnpj = db.Column(db.String(20))
        dest_cnpj = db.Column(db.String(20))
        emit_nome = db.Column(db.String(200))
        dest_nome = db.Column(db.String(200))
        numero = db.Column(db.String(20))
        serie = db.Column(db.String(20))

        valor_total = db.Column(db.Float, default=0.0)
        valor_produtos = db.Column(db.Float, default=0.0)
        icms = db.Column(db.Float, default=0.0)
        icms_st = db.Column(db.Float, default=0.0)
        ipi = db.Column(db.Float, default=0.0)
        pis = db.Column(db.Float, default=0.0)
        cofins = db.Column(db.Float, default=0.0)

        validation_status = db.Column(db.String(32))
        include_in_totals = db.Column(db.Boolean)
        processed_at = db.Column(db.DateTime)
        meta_json = db.Column(db.Text)

    return TestUserFile, TestNFESummary



# -------------------------------------------------------------------
# Utilitário: fábrica de um NFEXML fake com header/totais fixos
# -------------------------------------------------------------------
def make_fake_nfe(header: dict, totais: dict):
    class FakeNFEXML:
        def __init__(self, xml_bytes: bytes):
            self._xml = xml_bytes

        def header(self):
            return header

        def totais(self):
            return totais
    return FakeNFEXML


# -------------------------------------------------------------------
# Testes para _parse_emissao_iso
# -------------------------------------------------------------------
def test_parse_emissao_iso_variantes():
    # ISO com fuso -03:00
    s1 = "2025-09-21T09:00:00-03:00"
    d1 = _parse_emissao_iso(s1)
    assert isinstance(d1, dt.datetime)
    assert d1.tzinfo is None  # função remove tz se houver

    # ISO com Z (UTC)
    s2 = "2025-01-02T12:34:56Z"
    d2 = _parse_emissao_iso(s2)
    assert isinstance(d2, dt.datetime)
    assert d2.tzinfo is None

    # ISO naive
    s3 = "2025-09-21T09:00:00"
    d3 = _parse_emissao_iso(s3)
    assert isinstance(d3, dt.datetime)
    assert d3.tzinfo is None

    # vazio / inválido
    assert _parse_emissao_iso(None) is None
    assert _parse_emissao_iso("") is None
    assert _parse_emissao_iso("inválido") is None


# -------------------------------------------------------------------
# Testes para upsert_summary_from_xml
# -------------------------------------------------------------------
@pytest.fixture
def test_models(app):
    """Define os modelos de teste e cria suas tabelas."""
    TestUserFile, TestNFESummary = define_test_models()
    with app.app_context():
        db.create_all()
    return TestUserFile, TestNFESummary


def _default_header_em_totais(chave="CHAVE123"):
    header = {
        "chave": chave,
        "dhEmi": "2025-09-21T09:00:00-03:00",
        "emitente_cnpj": "11111111000191",
        "destinatario_cnpj": "22222222000172",
        "emitente_nome": "EMITENTE LTDA",
        "destinatario_nome": "DEST RECEPTOR SA",
        "numero": "987",
        "serie": "1",
    }
    totais = {
        "vNF": "1234.56",
        "vProd": "1000.00",
        "vICMS": "90.50",
        "vST": "0.00",
        "vIPI": "10.00",
        "vPIS": "5.55",
        "vCOFINS": "22.22",
    }
    return header, totais


def test_upsert_cria_summary_quando_nao_existe(db_session, user_normal, test_models):
    TestUserFile, TestNFESummary = test_models

    # Arrange: criar arquivo do usuário
    uf = TestUserFile(user_id=user_normal.id)
    db_session.add(uf); db_session.commit()

    header, totais = _default_header_em_totais("CHAVE_A")
    NFEXML = make_fake_nfe(header, totais)

    # Act
    summary, created = upsert_summary_from_xml(
        db=db, NFEXML=NFEXML, NFESummary=TestNFESummary, UserFile=TestUserFile,
        user_id=user_normal.id,
        xml_bytes=b"<nfe/>",
        user_file_id=uf.id
    )

    # Assert
    assert created is True
    assert summary.user_file_id == uf.id
    assert summary.chave == "CHAVE_A"
    assert summary.emissao is not None and isinstance(summary.emissao, dt.datetime)
    assert summary.emit_cnpj == header["emitente_cnpj"]
    assert summary.dest_cnpj == header["destinatario_cnpj"]
    assert summary.emit_nome == header["emitente_nome"]
    assert summary.dest_nome == header["destinatario_nome"]
    assert summary.numero == header["numero"]
    assert summary.serie == header["serie"]

    assert summary.valor_total == pytest.approx(1234.56)
    assert summary.valor_produtos == pytest.approx(1000.0)
    assert summary.icms == pytest.approx(90.5)
    assert summary.icms_st == pytest.approx(0.0)
    assert summary.ipi == pytest.approx(10.0)
    # Campos opcionais presentes no modelo
    #assert summary.pis == pytest.approx(5.55)
    #assert summary.cofins == pytest.approx(22.22)

    assert summary.validation_status == "pending"
    assert summary.include_in_totals is True
    assert summary.processed_at is not None

    meta = json.loads(summary.meta_json)
    assert meta["header"]["chave"] == "CHAVE_A"
    assert meta["totais"]["vNF"] == "1234.56"


def test_upsert_atualiza_summary_existente_por_user_file_id(db_session, user_normal, test_models):
    TestUserFile, TestNFESummary = test_models

    # Arrange: arquivo e summary existentes
    uf = TestUserFile(user_id=user_normal.id)
    db_session.add(uf); db_session.commit()

    s = TestNFESummary(
        user_file_id=uf.id,
        chave="CHAVE_B",
        valor_total=1.0,
        validation_status=None,
        include_in_totals=None,
        processed_at=None,
    )
    db_session.add(s); db_session.commit()

    # Novo XML com valores diferentes
    header, totais = _default_header_em_totais("CHAVE_B")
    header["dhEmi"] = "2025-09-01T10:20:30Z"  # outra forma de ISO
    totais.update({"vNF": "555.55", "vProd": "444.44", "vICMS": "33.33", "vST": "11.11", "vIPI": "2.22"})
    NFEXML = make_fake_nfe(header, totais)

    # Act
    summary, created = upsert_summary_from_xml(
        db=db, NFEXML=NFEXML, NFESummary=TestNFESummary, UserFile=TestUserFile,
        user_id=user_normal.id, xml_bytes=b"<nfe/>", user_file_id=uf.id
    )

    # Assert
    assert created is False
    assert summary.id == s.id  # mesma linha atualizada
    assert summary.valor_total == pytest.approx(555.55)
    assert summary.valor_produtos == pytest.approx(444.44)
    assert summary.icms == pytest.approx(33.33)
    assert summary.icms_st == pytest.approx(11.11)
    assert summary.ipi == pytest.approx(2.22)
    assert summary.validation_status == "pending"  # default preenchido
    assert summary.include_in_totals is True
    assert summary.processed_at is not None


def test_upsert_encontra_por_user_e_chave_quando_sem_user_file_id(db_session, user_normal, test_models):
    TestUserFile, TestNFESummary = test_models

    # Dois arquivos do mesmo usuário
    uf1 = TestUserFile(user_id=user_normal.id)
    uf2 = TestUserFile(user_id=user_normal.id)
    db_session.add_all([uf1, uf2]); db_session.commit()

    # Summary existente com a mesma chave, ligado ao uf1
    s = TestNFESummary(user_file_id=uf1.id, chave="CHAVE_C")
    db_session.add(s); db_session.commit()

    header, totais = _default_header_em_totais("CHAVE_C")
    NFEXML = make_fake_nfe(header, totais)

    # Act: chama SEM user_file_id; função deve encontrar pelo (user_id, chave)
    summary, created = upsert_summary_from_xml(
        db=db, NFEXML=NFEXML, NFESummary=TestNFESummary, UserFile=TestUserFile,
        user_id=user_normal.id, xml_bytes=b"<nfe/>", user_file_id=None
    )

    # Assert
    assert created is False
    assert summary.id == s.id
    # user_file_id permanece o original (uf1), pois não foi passado um novo
    assert summary.user_file_id == uf1.id


def test_upsert_erro_sem_chave(db_session, user_normal, test_models):
    TestUserFile, TestNFESummary = test_models
    uf = TestUserFile(user_id=user_normal.id)
    db_session.add(uf); db_session.commit()

    header = {
        # "chave" ausente
        "dhEmi": "2025-09-21T09:00:00-03:00",
        "emitente_cnpj": "11111111000191",
    }
    totais = {"vNF": "10.0"}
    NFEXML = make_fake_nfe(header, totais)

    with pytest.raises(ValueError, match="XML sem chave NF-e"):
        upsert_summary_from_xml(
            db=db, NFEXML=NFEXML, NFESummary=TestNFESummary, UserFile=TestUserFile,
            user_id=user_normal.id, xml_bytes=b"<nfe/>", user_file_id=uf.id
        )


def test_upsert_erro_sem_user_file_e_sem_match_por_chave(db_session, user_normal, test_models):
    TestUserFile, TestNFESummary = test_models

    # Nenhum summary criado e não vamos passar user_file_id
    header, totais = _default_header_em_totais("CHAVE_Z")
    NFEXML = make_fake_nfe(header, totais)

    with pytest.raises(ValueError, match="Não foi possível associar o XML a um arquivo do usuário"):
        upsert_summary_from_xml(
            db=db, NFEXML=NFEXML, NFESummary=TestNFESummary, UserFile=TestUserFile,
            user_id=user_normal.id, xml_bytes=b"<nfe/>", user_file_id=None
        )
# tests/test_nfexml_parser.py
import textwrap
from decimal import Decimal
import pytest

# Importe a classe/funções do seu módulo
# ajuste o caminho conforme a localização real do arquivo
from xml_parser import NFEXML, D, q2


# ---------- Helpers ----------
NS = "http://www.portalfiscal.inf.br/nfe"

def _wrap_nfe(inner_xml: str, with_proc: bool = False, add_id=True) -> bytes:
    """Monta um XML mínimo de NFe (ou nfeProc) com namespace oficial."""
    root_open = f'<NFe xmlns="{NS}"><infNFe Id="NFe123" versao="4.00">' if add_id else f'<NFe xmlns="{NS}"><infNFe versao="4.00">'
    root_close = "</infNFe></NFe>"
    if with_proc:
        return textwrap.dedent(f"""\
        <nfeProc xmlns="{NS}">
          {root_open}
          {inner_xml}
          {root_close}
        </nfeProc>
        """).encode("utf-8")
    else:
        return textwrap.dedent(f"""\
        {root_open}
        {inner_xml}
        {root_close}
        """).encode("utf-8")


# ---------- Testes de utilitários numéricos ----------
def test_D_parsing_and_q2_rounding():
    assert D("10") == Decimal("10")
    assert D("10,5") == Decimal("10.5")
    assert D("1.234,56") == Decimal("1234.56")
    assert D(None) == Decimal("0")
    assert D("invalido") == Decimal("0")
    assert q2("1,005") == Decimal("1.01")          # arredondamento HALF_UP
    assert q2("1,004") == Decimal("1.00")
    # idempotência com Decimal
    assert D(Decimal("2.3")) == Decimal("2.3")


# ---------- Testes de header() ----------
def test_header_with_namespace_and_dhEmi():
    inner = f"""
      <ide xmlns="{NS}">
        <nNF>987</nNF>
        <serie>1</serie>
        <mod>55</mod>
        <natOp>VENDA</natOp>
        <dhEmi>2025-09-21T09:00:00-03:00</dhEmi>
      </ide>
      <emit xmlns="{NS}">
        <xNome>EMITENTE LTDA</xNome>
        <CNPJ>11111111000191</CNPJ>
        <IE>ISENTO</IE>
        <enderEmit>
          <xLgr>Rua A</xLgr><nro>100</nro><xBairro>Centro</xBairro>
          <xMun>Manaus</xMun><UF>AM</UF><CEP>69000-000</CEP>
        </enderEmit>
      </emit>
      <dest xmlns="{NS}">
        <xNome>CLIENTE SA</xNome>
        <CNPJ>22222222000172</CNPJ>
        <IE>123</IE>
        <enderDest>
          <xLgr>Av B</xLgr><nro>200</nro><xBairro>Adrianópolis</xBairro>
          <xMun>Manaus</xMun><UF>AM</UF><CEP>69001-000</CEP>
        </enderDest>
      </dest>
    """
    xml = _wrap_nfe(inner, with_proc=True, add_id=True)
    nf = NFEXML(xml)
    h = nf.header()

    assert h["chave"] == "123"
    assert h["numero"] == "987"
    assert h["serie"] == "1"
    assert h["modelo"] == "55"
    assert h["natOp"] == "VENDA"
    assert h["dhEmi"].startswith("2025-09-21")

    assert h["emitente_nome"] == "EMITENTE LTDA"
    assert h["emitente_cnpj"] == "11111111000191"
    assert h["emitente_endereco"] == "Rua A, 100, Centro"
    assert h["emitente_municipio"] == "Manaus"
    assert h["emitente_uf"] == "AM"

    assert h["dest_nome"] == "CLIENTE SA"
    assert h["dest_cnpj"] == "22222222000172"
    assert h["dest_endereco"] == "Av B, 200, Adrianópolis"
    assert h["dest_uf"] == "AM"

    assert h["uf_origem"] == "AM" and h["uf_destino"] == "AM"


def test_header_uses_dEmi_when_dhEmi_missing():
    inner = f"""
      <ide xmlns="{NS}">
        <nNF>1</nNF><serie>1</serie><mod>55</mod><natOp>VENDA</natOp>
        <dEmi>2025-05-01</dEmi>
      </ide>
    """
    xml = _wrap_nfe(inner, with_proc=False, add_id=False)
    nf = NFEXML(xml)
    h = nf.header()
    assert h["chave"] == ""            # sem Id
    assert h["dhEmi"] == "2025-05-01"  # caiu no fallback dEmi


# ---------- Testes de totais() ----------
def test_totais_reads_icmstot():
    inner = f"""
      <total xmlns="{NS}">
        <ICMSTot>
          <vProd>1000,00</vProd><vFrete>50,00</vFrete><vIPI>10,00</vIPI>
          <vDesc>5,00</vDesc><vOutro>2,00</vOutro><vICMSDeson>1,00</vICMSDeson>
          <vICMS>90,50</vICMS><vST>0,00</vST><vNF>1057,50</vNF>
        </ICMSTot>
      </total>
    """
    xml = _wrap_nfe(inner)
    nf = NFEXML(xml)
    t = nf.totais()
    assert t["vProd"] == pytest.approx(1000.00)
    assert t["vFrete"] == pytest.approx(50.00)
    assert t["vIPI"] == pytest.approx(10.00)
    assert t["vNF"] == pytest.approx(1057.50)


# ---------- Testes de itens() ----------
def test_itens_with_item_frete_and_taxes():
    inner = f"""
      <det xmlns="{NS}" nItem="1">
        <prod>
          <cProd>A1</cProd><xProd>Produto A</xProd><NCM>1234</NCM><CFOP>5102</CFOP>
          <uCom>UN</uCom><uTrib>UN</uTrib><cEAN>SEM GTIN</cEAN><cEANTrib></cEANTrib>
          <qCom>2,0000</qCom><vUnCom>10,00</vUnCom><vFrete>3,00</vFrete>
        </prod>
        <imposto>
          <ICMS><ICMS00><CST>00</CST><vICMSDeson>0,50</vICMSDeson></ICMS00></ICMS>
          <IPI><IPITrib><vIPI>1,00</vIPI></IPITrib></IPI>
        </imposto>
      </det>
      <total xmlns="{NS}">
        <ICMSTot><vProd>20,00</vProd><vFrete>10,00</vFrete><vOutro>2,00</vOutro></ICMSTot>
      </total>
    """
    xml = _wrap_nfe(inner)
    nf = NFEXML(xml)
    itens = nf.itens()
    assert len(itens) == 1
    it = itens[0]
    assert it.cProd == "A1" and it.xProd == "Produto A"
    assert it.qCom == Decimal("2.00")
    assert it.vUnCom == Decimal("10.00")
    assert it.vProd == Decimal("20.00")
    # Como item possui vFrete, usa o do item (3,00), arredondado:
    assert it.vFrete == Decimal("3.00")
    # vOutro rateado: total 2,00 todo para o único item
    assert it.vOutro == Decimal("2.00")
    # IPI e ICMS desonerado:
    assert it.vIPI == Decimal("1.00")
    assert it.vICMSDeson == Decimal("0.50")


def test_itens_rateio_frete_sem_frete_item():
    inner = f"""
      <det xmlns="{NS}" nItem="1">
        <prod>
          <cProd>A1</cProd><xProd>Prod A</xProd><NCM>1234</NCM><CFOP>5102</CFOP>
          <qCom>1</qCom><vUnCom>100,00</vUnCom>
        </prod>
        <imposto><ICMS><ICMS00><CST>00</CST></ICMS00></ICMS></imposto>
      </det>
      <det xmlns="{NS}" nItem="2">
        <prod>
          <cProd>B2</cProd><xProd>Prod B</xProd><NCM>1234</NCM><CFOP>5102</CFOP>
          <qCom>3</qCom><vUnCom>50,00</vUnCom>
        </prod>
        <imposto><ICMS><ICMS00><CST>00</CST></ICMS00></ICMS></imposto>
      </det>
      <total xmlns="{NS}">
        <ICMSTot><vProd>250,00</vProd><vFrete>25,00</vFrete><vOutro>0,00</vOutro></ICMSTot>
      </total>
    """
    xml = _wrap_nfe(inner)
    nf = NFEXML(xml)
    itens = nf.itens()
    assert len(itens) == 2

    # vProd: item1=100; item2=150
    it1, it2 = itens
    assert it1.vProd == Decimal("100.00")
    assert it2.vProd == Decimal("150.00")

    # rateio do frete 25 proporcional a vProd:
    # it1: 25 * (100/250) = 10,00
    # it2: 25 * (150/250) = 15,00
    assert it1.vFrete == Decimal("10.00")
    assert it2.vFrete == Decimal("15.00")


# ---------- Transporte, cobrança, duplicatas, inf_adic ----------
def test_transporte_cobranca_duplicatas_and_inf_adic():
    inner = f"""
      <transp xmlns="{NS}">
        <modFrete>1</modFrete>
        <transporta>
          <xNome>TRANSP X</xNome><CNPJ>33333333000100</CNPJ><UF>AM</UF>
        </transporta>
        <vol><qVol>5</qVol><esp>CAIXA</esp><marca>ACME</marca><nVol>1</nVol><pesoL>10</pesoL><pesoB>11</pesoB></vol>
      </transp>
      <cobr xmlns="{NS}">
        <fat><nFat>F123</nFat><vOrig>100,00</vOrig><vDesc>5,00</vDesc><vLiq>95,00</vLiq></fat>
        <dup><nDup>001</nDup><dVenc>2025-10-30</dVenc><vDup>50,00</vDup></dup>
        <dup><nDup>002</nDup><dVenc>2025-11-30</dVenc><vDup>45,00</vDup></dup>
      </cobr>
      <infAdic xmlns="{NS}">
        <infCpl>Observações adicionais do documento.</infCpl>
      </infAdic>
    """
    xml = _wrap_nfe(inner)
    nf = NFEXML(xml)

    tr = nf.transporte()
    assert tr["modFrete"] == "1"
    assert tr["transportadora_nome"] == "TRANSP X"
    assert tr["transportadora_cnpj"] == "33333333000100"
    assert tr["qVol"] == "5"
    assert tr["esp"] == "CAIXA"
    assert tr["marca"] == "ACME"

    cb = nf.cobranca()
    assert cb["nFat"] == "F123"
    assert cb["vOrig"] == pytest.approx(100.00)
    assert cb["vDesc"] == pytest.approx(5.00)
    assert cb["vLiq"] == pytest.approx(95.00)

    dups = nf.duplicatas()
    assert len(dups) == 2
    assert dups[0]["nDup"] == "001" and dups[1]["nDup"] == "002"
    assert dups[0]["vDup"] == pytest.approx(50.00)

    ia = nf.inf_adic()
    assert "Observações adicionais" in ia
