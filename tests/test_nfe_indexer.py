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
