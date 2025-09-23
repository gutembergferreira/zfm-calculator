import io
import hashlib
import requests
import pandas as pd
from datetime import datetime
from sheets import SheetClient

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
def write_to_sheets(tables: dict, sh: SheetClient):
    for name, df in tables.items():
        sh.write_df(name, df)

def run_update_am(sheet_client: SheetClient):
    ts = datetime.now().isoformat(timespec="seconds")
    nome = "ST AM – XLSX"
    try:
        df_raw = fetch_st_am_xlsx()
        version = _version_hash(df_raw)
        tables = normalize_st_am(df_raw)
        write_to_sheets(tables, sheet_client)
        status, msg, n = "OK", "Atualizado via XLSX SEFAZ/AM", len(df_raw)
    except Exception as e:
        status, msg, n, version = "ERRO", str(e), 0, ""

    # log (best-effort)
    try:
        sheet_client.append_row("sources_log", [ts, "AM", nome, status, msg, n, version])
    except Exception:
        pass
