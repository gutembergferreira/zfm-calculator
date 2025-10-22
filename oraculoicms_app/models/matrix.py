from __future__ import annotations

from datetime import datetime

from oraculoicms_app.extensions import db


class Aliquota(db.Model):
    __tablename__ = "aliquotas"

    id = db.Column(db.Integer, primary_key=True)
    uf = db.Column(db.String(2), nullable=False)
    tipo = db.Column(db.String(32), nullable=False)
    uf_dest = db.Column(db.String(2), nullable=True)
    aliquota = db.Column(db.Numeric(10, 4), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Mva(db.Model):
    __tablename__ = "mva"

    id = db.Column(db.Integer, primary_key=True)
    ncm = db.Column(db.String(20), nullable=False, index=True)
    segmento = db.Column(db.String(120), nullable=True)
    mva = db.Column(db.Numeric(10, 4), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Multiplicador(db.Model):
    __tablename__ = "multiplicadores"

    id = db.Column(db.Integer, primary_key=True)
    ncm = db.Column(db.String(20), nullable=False, index=True)
    regiao = db.Column(db.String(50), nullable=True)
    multiplicador = db.Column(db.Numeric(10, 4), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class CreditoPresumido(db.Model):
    __tablename__ = "creditos_presumidos"

    id = db.Column(db.Integer, primary_key=True)
    ncm = db.Column(db.String(20), nullable=False, index=True)
    regra = db.Column(db.String(120), nullable=True)
    percentual = db.Column(db.Numeric(10, 4), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class STRegra(db.Model):
    __tablename__ = "st_regras"

    id = db.Column(db.Integer, primary_key=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    ncm = db.Column(db.String(20), nullable=False, index=True)
    cest = db.Column(db.String(20), nullable=True)
    cst_incluir = db.Column(db.String(120), nullable=True)
    cst_excluir = db.Column(db.String(120), nullable=True)
    cfop_ini = db.Column(db.String(10), nullable=True)
    cfop_fim = db.Column(db.String(10), nullable=True)
    st_aplica = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ConfigParametro(db.Model):
    __tablename__ = "config"

    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.String(255), nullable=True)


class Source(db.Model):
    __tablename__ = "sources"

    id = db.Column(db.Integer, primary_key=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    uf = db.Column(db.String(2), nullable=True)
    nome = db.Column(db.String(120), nullable=False)
    url = db.Column(db.String(255), nullable=True)
    tipo = db.Column(db.String(50), nullable=True)
    parser = db.Column(db.String(120), nullable=True)
    prioridade = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class SourceLog(db.Model):
    __tablename__ = "sources_log"

    id = db.Column(db.Integer, primary_key=True)
    executado_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    uf = db.Column(db.String(2), nullable=True)
    nome = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    mensagem = db.Column(db.Text, nullable=True)
    linhas = db.Column(db.Integer, nullable=True)
    versao = db.Column(db.String(64), nullable=True)


__all__ = [
    "Aliquota",
    "Mva",
    "Multiplicador",
    "CreditoPresumido",
    "STRegra",
    "ConfigParametro",
    "Source",
    "SourceLog",
]
