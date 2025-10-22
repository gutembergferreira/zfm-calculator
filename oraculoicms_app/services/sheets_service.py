from __future__ import annotations

from typing import Any, Dict

import pandas as pd
from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from oraculoicms_app.extensions import db
from oraculoicms_app.models.matrix import (
    Aliquota,
    ConfigParametro,
    CreditoPresumido,
    Mva,
    Multiplicador,
    Source,
    SourceLog,
    STRegra,
)


def _coerce_bool(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    return value


def _query_to_dataframe(model, mapping: Dict[str, str]) -> pd.DataFrame:
    try:
        rows = db.session.execute(select(model)).scalars().all()
    except SQLAlchemyError:
        return pd.DataFrame(columns=list(mapping.keys()))

    data = []
    for row in rows:
        record = {}
        for column, attribute in mapping.items():
            record[column] = _coerce_bool(getattr(row, attribute))
        data.append(record)
    return pd.DataFrame(data, columns=list(mapping.keys()))


def _load_matrices() -> Dict[str, pd.DataFrame]:
    matrices: Dict[str, pd.DataFrame] = {
        "aliquotas": _query_to_dataframe(
            Aliquota,
            {"UF": "uf", "TIPO": "tipo", "UF_DEST": "uf_dest", "ALIQ": "aliquota"},
        ),
        "mva": _query_to_dataframe(
            Mva,
            {"NCM": "ncm", "SEGMENTO": "segmento", "MVA": "mva"},
        ),
        "multiplicadores": _query_to_dataframe(
            Multiplicador,
            {"NCM": "ncm", "REGIAO": "regiao", "MULT": "multiplicador"},
        ),
        "creditos_presumidos": _query_to_dataframe(
            CreditoPresumido,
            {"NCM": "ncm", "REGRA": "regra", "PERC": "percentual"},
        ),
        "config": _query_to_dataframe(
            ConfigParametro,
            {"CHAVE": "chave", "VALOR": "valor"},
        ),
        "st_regras": _query_to_dataframe(
            STRegra,
            {
                "ATIVO": "ativo",
                "NCM": "ncm",
                "CEST": "cest",
                "CST_INCLUIR": "cst_incluir",
                "CST_EXCLUIR": "cst_excluir",
                "CFOP_INI": "cfop_ini",
                "CFOP_FIM": "cfop_fim",
                "ST_APLICA": "st_aplica",
            },
        ),
        "sources": _query_to_dataframe(
            Source,
            {
                "ATIVO": "ativo",
                "UF": "uf",
                "NOME": "nome",
                "URL": "url",
                "TIPO": "tipo",
                "PARSER": "parser",
                "PRIORIDADE": "prioridade",
            },
        ),
        "sources_log": _query_to_dataframe(
            SourceLog,
            {
                "EXECUTADO_EM": "executado_em",
                "UF": "uf",
                "NOME": "nome",
                "STATUS": "status",
                "MENSAGEM": "mensagem",
                "LINHAS": "linhas",
                "VERSAO": "versao",
            },
        ),
    }

    return matrices


def init_sheets(app) -> None:
    app.extensions.setdefault("sheet_client", None)
    app.extensions.setdefault("matrices", {})
    app.extensions.setdefault("worksheets", [])

    with app.app_context():
        app.extensions["matrices"] = _load_matrices()


def get_sheet_client():
    return current_app.extensions.get("sheet_client")


def get_matrices():
    return current_app.extensions.get("matrices", {})


def reload_matrices():
    matrices = _load_matrices()
    current_app.extensions["matrices"] = matrices
    return matrices
