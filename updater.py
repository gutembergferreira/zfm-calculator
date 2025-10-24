import io
import hashlib
import re
from datetime import datetime
from decimal import Decimal

import pandas as pd
import requests
from html.parser import HTMLParser
from sqlalchemy import delete

from oraculoicms_app.extensions import db
from oraculoicms_app.models.matrix import Mva, Multiplicador, STRegra, SourceLog

SEFAZ_AM_HTML = "https://sistemas.sefaz.am.gov.br/get/Normas.do?metodo=viewDoc&uuidDoc=84be7172-451e-4ca0-802e-1a0303e5f0b2"
SEFAZ_AM_XLSX = "https://online.sefaz.am.gov.br/sinf2004/DI/Tabela%20ST%20-%20Atualizada%20pela%20Lei%206108-22.xlsx"


# ---------- helpers ----------
def _version_hash(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    m = hashlib.sha256()
    m.update(pd.util.hash_pandas_object(df.fillna(""), index=True).values)
    return m.hexdigest()[:16]


def _compact_text(text) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def _find_column(df: pd.DataFrame, *keywords: str) -> str | None:
    upper_keywords = tuple(k.upper() for k in keywords)
    for col in df.columns:
        col_upper = str(col).upper()
        if all(k in col_upper for k in upper_keywords):
            return col
    return None


def _normalize_ncm(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits or _compact_text(value)


def _normalize_cest(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits


def is_truthy(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    text = str(value).strip().upper()
    return text in {"1", "TRUE", "T", "SIM", "S", "Y", "YES", "ON"}


def _interpret_st_flag(value) -> bool:
    if is_truthy(value):
        return True
    text = _compact_text(value).upper()
    if not text:
        return False
    if any(term in text for term in ("NAO", "NÃO", "NAO SE APLICA", "NÃO SE APLICA")):
        return False
    if "SUBSTIT" in text or "SUJEITO" in text:
        return True
    return False


def _clean_numeric(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return Decimal(str(value)) if value != "" else None


# ---------- fetch & normalize ----------
def fetch_st_am_html() -> str:
    resp = requests.get(SEFAZ_AM_HTML, timeout=60)
    resp.raise_for_status()
    if not resp.encoding and resp.apparent_encoding:
        resp.encoding = resp.apparent_encoding
    return resp.text


class _TableExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._capture_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._buffer = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self._in_table:
                # nested tables: finalize current and start a new
                self._close_table()
            self._in_table = True
            self._current_table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_row and tag in {"td", "th"}:
            self._capture_cell = True
            self._buffer = ""

    def handle_data(self, data):
        if self._capture_cell:
            self._buffer += data

    def handle_endtag(self, tag):
        if self._capture_cell and tag in {"td", "th"}:
            text = _compact_text(self._buffer)
            self._current_row.append(text)
            self._capture_cell = False
        elif self._in_row and tag == "tr":
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._in_row = False
        elif self._in_table and tag == "table":
            self._close_table()

    def _close_table(self):
        if self._current_table:
            self.tables.append(self._current_table)
        self._in_table = False
        self._in_row = False
        self._capture_cell = False
        self._current_table = []
        self._current_row = []
        self._buffer = ""


def parse_st_am_html(html: str) -> pd.DataFrame:
    parser = _TableExtractor()
    parser.feed(html)
    tables: list[pd.DataFrame] = []

    for raw_table in parser.tables:
        if not raw_table:
            continue
        header = raw_table[0]
        if not any("NCM" in str(h).upper() for h in header):
            continue
        normalized_header = [str(h).strip() for h in header]
        mapped_rows = []
        for raw_row in raw_table[1:]:
            if all(not _compact_text(cell) for cell in raw_row):
                continue
            values = raw_row[: len(normalized_header)]
            if len(values) < len(normalized_header):
                values += [""] * (len(normalized_header) - len(values))
            mapped_rows.append(dict(zip(normalized_header, values)))

        if mapped_rows:
            df = pd.DataFrame(mapped_rows)
            df.columns = [str(c).strip().upper() for c in df.columns]
            tables.append(df)

    if not tables:
        raise ValueError("Nenhuma tabela de NCM encontrada no HTML da SEFAZ/AM.")

    tables.sort(key=lambda frame: len(frame.index), reverse=True)
    return tables[0]


def fetch_st_am_xlsx() -> pd.DataFrame:
    r = requests.get(SEFAZ_AM_XLSX, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), engine="openpyxl")
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def normalize_st_am(df: pd.DataFrame) -> dict:
    df = df.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]

    ncm_col = _find_column(df, "NCM")
    if not ncm_col:
        raise ValueError("Coluna NCM não encontrada nos dados da SEFAZ/AM.")
    cest_col = _find_column(df, "CEST")
    mva_col = _find_column(df, "MVA")
    regime_col = _find_column(df, "REGIME") or _find_column(df, "SUBSTITU")
    aplica_col = _find_column(df, "SUBSTITU") if not regime_col else None

    tables: dict[str, pd.DataFrame] = {}

    if mva_col:
        mva = df.loc[df[mva_col].notna(), [ncm_col, mva_col]].copy()
        if not mva.empty:
            mva = mva.rename(columns={ncm_col: "NCM", mva_col: "MVA"})
            mva["MVA"] = pd.to_numeric(mva["MVA"], errors="coerce").fillna(0.0)
            tables["mva"] = mva

    multiplicadores = pd.DataFrame()
    if not multiplicadores.empty:
        tables["multiplicadores"] = multiplicadores

    st = pd.DataFrame()
    st["NCM"] = df[ncm_col].apply(_normalize_ncm)
    st["CEST"] = df[cest_col].apply(_normalize_cest) if cest_col else ""

    def _extract_aplica(row):
        if regime_col:
            value = row.get(regime_col)
        elif aplica_col:
            value = row.get(aplica_col)
        else:
            value = None
        return 1 if _interpret_st_flag(value) else 0

    st["ST_APLICA"] = df.apply(_extract_aplica, axis=1)
    st["ATIVO"] = st["ST_APLICA"].apply(lambda v: 1 if v else 0)
    st["CST_INCLUIR"] = ""
    st["CST_EXCLUIR"] = "40,41,50"
    st["CFOP_INI"] = ""
    st["CFOP_FIM"] = ""

    st = st[st["NCM"].astype(str).str.strip() != ""].copy()
    if st.empty:
        raise ValueError("Nenhuma regra ST encontrada nos dados normalizados.")

    st_regras_cols = [
        "ATIVO",
        "NCM",
        "CEST",
        "CST_INCLUIR",
        "CST_EXCLUIR",
        "CFOP_INI",
        "CFOP_FIM",
        "ST_APLICA",
    ]
    tables["st_regras"] = st[st_regras_cols].copy()
    return tables


# ---------- writer & runner ----------
def write_to_database(tables: dict):
    with db.session.begin():
        if "mva" in tables:
            df = tables["mva"].fillna("")
            db.session.execute(delete(Mva))
            for row in df.to_dict(orient="records"):
                db.session.add(Mva(
                    ncm=str(row.get("NCM", "")),
                    segmento=row.get("SEGMENTO") or None,
                    mva=_clean_numeric(row.get("MVA")) or Decimal("0"),
                ))

        if "multiplicadores" in tables:
            df = tables["multiplicadores"].fillna("")
            db.session.execute(delete(Multiplicador))
            for row in df.to_dict(orient="records"):
                db.session.add(Multiplicador(
                    ncm=str(row.get("NCM", "")),
                    regiao=row.get("REGIAO") or None,
                    multiplicador=_clean_numeric(row.get("MULT")) or Decimal("0"),
                ))

        if "st_regras" in tables:
            df = tables["st_regras"].fillna("")
            db.session.execute(delete(STRegra))
            for row in df.to_dict(orient="records"):
                db.session.add(STRegra(
                    ativo=is_truthy(row.get("ATIVO")),
                    ncm=str(row.get("NCM", "")),
                    cest=row.get("CEST") or None,
                    cst_incluir=row.get("CST_INCLUIR") or None,
                    cst_excluir=row.get("CST_EXCLUIR") or None,
                    cfop_ini=row.get("CFOP_INI") or None,
                    cfop_fim=row.get("CFOP_FIM") or None,
                    st_aplica=is_truthy(row.get("ST_APLICA")),
                ))


def run_update_am():
    dt_now = datetime.now()
    status = "ERRO"
    msg = ""
    n = 0
    version = ""
    nome = "ST AM – HTML"

    html_error: Exception | None = None
    try:
        html = fetch_st_am_html()
        df_raw = parse_st_am_html(html)
        version = _version_hash(df_raw)
        tables = normalize_st_am(df_raw)
        write_to_database(tables)
        status = "OK"
        msg = "Atualizado via HTML SEFAZ/AM"
        n = len(df_raw.index)
    except Exception as err_html:
        html_error = err_html
        nome = "ST AM – XLSX"
        try:
            df_raw = fetch_st_am_xlsx()
            version = _version_hash(df_raw)
            tables = normalize_st_am(df_raw)
            write_to_database(tables)
            status = "OK"
            msg = "Atualizado via XLSX SEFAZ/AM (fallback)"
            if html_error:
                msg += f"; HTML: {html_error}"
            n = len(df_raw.index)
        except Exception as err_xlsx:
            status = "ERRO"
            msg = f"HTML: {html_error}; XLSX: {err_xlsx}"
            n = 0
            version = ""

    try:
        with db.session.begin():
            db.session.add(SourceLog(
                executado_em=dt_now,
                uf="AM",
                nome=nome,
                status=status,
                mensagem=msg,
                linhas=n,
                versao=version,
            ))
    except Exception:
        db.session.rollback()
