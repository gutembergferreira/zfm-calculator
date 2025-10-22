import io
import hashlib
import requests
import pandas as pd
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete

from oraculoicms_app.extensions import db
from oraculoicms_app.models.matrix import Mva, Multiplicador, STRegra, SourceLog

SEFAZ_AM_XLSX = "https://online.sefaz.am.gov.br/sinf2004/DI/Tabela%20ST%20-%20Atualizada%20pela%20Lei%206108-22.xlsx"

# ---------- helpers ----------
def _version_hash(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    m = hashlib.sha256()
    m.update(pd.util.hash_pandas_object(df.fillna(""), index=True).values)
    return m.hexdigest()[:16]

# ---------- fetch & normalize ----------
def fetch_st_am_xlsx() -> pd.DataFrame:
    r = requests.get(SEFAZ_AM_XLSX, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), engine="openpyxl")
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df

def normalize_st_am(df: pd.DataFrame) -> dict:
    """
    Ajuste este mapeamento após conferir os headers reais da planilha SEFAZ/AM.
    Exemplos de colunas esperadas:
      - "NCM/SH"   -> NCM
      - "CEST"     -> CEST
      - "MVA"      -> MVA (percentual)
      - "REGIME"   -> texto com 'Substituição' quando aplicável
    """
    ncm_col = "NCM/SH" if "NCM/SH" in df.columns else ("NCM" if "NCM" in df.columns else None)
    cest_col = "CEST" if "CEST" in df.columns else None
    mva_col  = "MVA" if "MVA" in df.columns else None
    regime_col = "REGIME" if "REGIME" in df.columns else None

    # MVA
    if mva_col and ncm_col:
        mva = df.loc[df[mva_col].notna(), [ncm_col, mva_col]].copy()
        mva = mva.rename(columns={ncm_col: "NCM", mva_col: "MVA"})
        mva["MVA"] = pd.to_numeric(mva["MVA"], errors="coerce").fillna(0.0)
    else:
        mva = pd.DataFrame(columns=["NCM", "MVA"])

    # Multiplicadores (se houver colunas específicas você ajusta aqui)
    multiplicadores = pd.DataFrame(columns=["NCM", "MULT"])

    # Regras ST (aplicabilidade por NCM/CEST)
    st_regras_cols = ["ATIVO", "NCM", "CEST", "CST_INCLUIR", "CST_EXCLUIR", "CFOP_INI", "CFOP_FIM", "ST_APLICA"]
    st = pd.DataFrame()
    st["NCM"] = df[ncm_col] if ncm_col else ""
    st["CEST"] = df[cest_col] if cest_col else ""
    if regime_col:
        aplica = df[regime_col].astype(str).str.contains("SUBSTITU", case=False, na=False).astype(int)
    else:
        aplica = 0
    st["ST_APLICA"] = aplica
    st["ATIVO"] = 1
    st["CST_INCLUIR"] = ""       # pode refinar depois
    st["CST_EXCLUIR"] = "40,41,50"  # exemplo de exclusões comuns
    st["CFOP_INI"] = ""
    st["CFOP_FIM"] = ""
    st_regras = st[st_regras_cols].copy()

    return {
        "mva": mva,
        "multiplicadores": multiplicadores,
        "st_regras": st_regras,
    }

# ---------- writer & runner ----------
def _is_truthy(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    text = str(value).strip().upper()
    return text in {"1", "TRUE", "T", "SIM", "S", "Y", "YES", "ON"}


def _clean_numeric(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return Decimal(str(value)) if value != "" else None


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
                    ativo=_is_truthy(row.get("ATIVO")),
                    ncm=str(row.get("NCM", "")),
                    cest=row.get("CEST") or None,
                    cst_incluir=row.get("CST_INCLUIR") or None,
                    cst_excluir=row.get("CST_EXCLUIR") or None,
                    cfop_ini=row.get("CFOP_INI") or None,
                    cfop_fim=row.get("CFOP_FIM") or None,
                    st_aplica=_is_truthy(row.get("ST_APLICA")),
                ))


def run_update_am():
    dt_now = datetime.now()
    ts = dt_now.isoformat(timespec="seconds")
    nome = "ST AM – XLSX"
    try:
        df_raw = fetch_st_am_xlsx()
        version = _version_hash(df_raw)
        tables = normalize_st_am(df_raw)
        write_to_database(tables)
        status, msg, n = "OK", "Atualizado via XLSX SEFAZ/AM", len(df_raw)
    except Exception as e:
        status, msg, n, version = "ERRO", str(e), 0, ""

    # log (best-effort)
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
