from dataclasses import dataclass
from typing import Dict, Any
import pandas as pd

@dataclass
class ItemNF:
    ncm: str
    cfop: str
    cst: str
    valor_produto: float
    frete_rateado: float
    descontos: float
    despesas_acessorias: float
    icms_destacado_origem: float
    icms_desonerado: float = 0.0
    motivo_desoneracao: str = ""
    cest: str = ""

@dataclass
class ResultadoItem:
    base_calculo_st: float
    icms_st_devido: float
    memoria: Dict[str, Any]

# ---------------- helpers ----------------

def _f(x: float) -> float:
    try:
        return float(x or 0.0)
    except Exception:
        return 0.0


def _to_float(val, default=0.0):
    try:
        if val is None:
            return default
        s = str(val).strip().replace("%","").replace(" ","").replace(",",".")
        return float(s)
    except Exception:
        return default

def _to_percent(val, default=0.0):
    x = _to_float(val, default)
    return x*100.0 if x <= 1.0 else x

def _norm_ncm(ncm: str) -> str:
    return "".join(ch for ch in str(ncm) if ch.isdigit())

def _best_prefix_row(df: pd.DataFrame, col_ncm: str, ncm_key: str) -> pd.Series | None:
    if df.empty or not ncm_key:
        return None
    t = df.copy()
    t["_NCM_KEY"] = t[col_ncm].astype(str).map(_norm_ncm)
    t = t[t["_NCM_KEY"].apply(lambda k: bool(k) and ncm_key.startswith(k))]
    if t.empty:
        return None
    t["_LEN"] = t["_NCM_KEY"].str.len()
    t = t.sort_values("_LEN", ascending=False)
    return t.iloc[0]

# -------------- motor --------------------
class MotorCalculo:
    """
    Abas esperadas em matrices:
      - aliquotas: UF | TIPO | UF_DEST | ALIQ  (ALIQ decimal: 0.20)
      - mva: NCM (ou prefixo) | MVA             (pode vir fração 0.5 => 50%)
      - multiplicadores: NCM (ou prefixo) | MULT (fração ou %)
      - creditos_presumidos: NCM (ou prefixo) | UF_DEST | TIPO | PERC (decimal)
      - config: CHAVE | VALOR (DEFAULT_ALI_INT, DEFAULT_ALI_INTER)
    """
    def __init__(self, matrices: Dict[str, pd.DataFrame]):
        self.m = matrices

    def _cfg_default(self, key: str, fallback: float) -> float:
        cfg = self.m.get("config")
        if cfg is None or cfg.empty:
            return fallback
        df = cfg.rename(columns={c: str(c).strip().upper() for c in cfg.columns})
        if not {"CHAVE","VALOR"}.issubset(df.columns):
            return fallback
        row = df.loc[df["CHAVE"]==key].head(1)
        if row.empty: return fallback
        return _to_float(row["VALOR"].iloc[0], fallback)

    def _busca_param(self, ncm: str, uf_origem: str, uf_destino: str) -> Dict[str, float]:
        ncm_key = _norm_ncm(ncm)

        # MVA
        mva = 0.0
        df_mva = self.m.get("mva")
        if df_mva is not None and not df_mva.empty:
            df = df_mva.rename(columns={c: str(c).strip().upper() for c in df_mva.columns}).copy()
            row = None
            if "NCM" in df.columns:
                row = _best_prefix_row(df, "NCM", ncm_key)
            if row is not None and "MVA" in df.columns:
                mva = _to_percent(row["MVA"])  # fração -> %

        # MULT
        mult = 0.0
        df_mult = self.m.get("multiplicadores")
        if df_mult is not None and not df_mult.empty:
            df = df_mult.rename(columns={c: str(c).strip().upper() for c in df_mult.columns}).copy()
            row = None
            if "NCM" in df.columns:
                row = _best_prefix_row(df, "NCM", ncm_key)
            if row is not None and "MULT" in df.columns:
                mult = _to_percent(row["MULT"])

        # Aliquotas
        ali_int = self._cfg_default("DEFAULT_ALI_INT", 0.18)
        ali_inter = self._cfg_default("DEFAULT_ALI_INTER", 0.12)
        df_ali = self.m.get("aliquotas")
        if df_ali is not None and not df_ali.empty:
            df = df_ali.rename(columns={c: str(c).strip().upper() for c in df_ali.columns}).copy()
            q = df.loc[(df["UF"]==uf_destino) & (df["TIPO"].str.upper()=="INTERNA")].head(1)
            if not q.empty: ali_int = _to_float(q["ALIQ"].iloc[0], ali_int)
            q = df.loc[(df["UF"]==uf_origem) & (df["TIPO"].str.upper()=="INTERESTADUAL") & (df["UF_DEST"]==uf_destino)].head(1)
            if not q.empty: ali_inter = _to_float(q["ALIQ"].iloc[0], ali_inter)

        # Crédito presumido
        cred_perc = 0.0; cred_tipo = "SOBRE_DEBITO"
        df_cp = self.m.get("creditos_presumidos")
        if df_cp is not None and not df_cp.empty:
            df = df_cp.rename(columns={c: str(c).strip().upper() for c in df_cp.columns}).copy()
            row = None
            if "NCM" in df.columns:
                row = _best_prefix_row(df, "NCM", ncm_key)
            if row is not None:
                cred_perc = _to_float(row.get("PERC",0.0),0.0)
                t = str(row.get("TIPO","SOBRE_DEBITO")).strip().upper()
                if t in ("SOBRE_DEBITO","SOBRE_BASE"): cred_tipo = t

        return {
            "MVA": mva,            # %
            "MULT": mult,          # %
            "ALI_INT": ali_int,    # decimal
            "ALI_INTER": ali_inter,# decimal
            "CRED_PERC": cred_perc,# decimal
            "CRED_TIPO": cred_tipo,
        }

    # calc.py — dentro da classe MotorCalculo



    def calcula_st(self, item: "ItemNF", uf_origem: str, uf_destino: str,
                   usar_multiplicador: bool = True) -> "ResultadoItem":
        # Busca parâmetros como você já faz hoje
        p = self._busca_param(item.ncm, uf_origem, uf_destino)

        memoria = {"parametros": p}

        # --------- Campos “de entrada” (para exibir) ----------
        sequencial_item = int(getattr(item, "nItem", 0))
        cod_produto = getattr(item, "cProd", "")
        descricao = getattr(item, "xProd", "")
        ncm = getattr(item, "ncm", "")
        quant = _f(getattr(item, "qCom", 0.0))
        valor_unit = _f(getattr(item, "vUnCom", 0.0))
        vlr_total_prod = _f(getattr(item, "vProd", 0.0))
        frete = _f(getattr(item, "vFrete", 0.0) if hasattr(item, "vFrete") else getattr(item, "frete_rateado", 0.0))
        ipi = _f(getattr(item, "vIPI", 0.0) if hasattr(item, "vIPI") else getattr(item, "ipi", 0.0))
        desp_aces = _f(
            getattr(item, "vOutro", 0.0) if hasattr(item, "vOutro") else getattr(item, "despesas_acessorias", 0.0))
        descontos = _f(getattr(item, "vDesc", 0.0) if hasattr(item, "vDesc") else getattr(item, "descontos", 0.0))
        icms_desonerado = _f(
            getattr(item, "vICMSDeson", 0.0) if hasattr(item, "vICMSDeson") else getattr(item, "icms_desonerado", 0.0))
        icms_dest_origem = _f(
            getattr(item, "vICMS", 0.0) if hasattr(item, "vICMS") else getattr(item, "icms_destacado_origem", 0.0))

        # --------- Cálculos base alinhados ao que você quer ver ----------
        # Valor da venda com desconto de ICMS (conferência)
        valor_venda_com_desc_icms = vlr_total_prod - icms_desonerado

        # Valor da Operação = Produto + Frete + Desp.Acess. + IPI - Descontos
        valor_operacao = vlr_total_prod + frete + desp_aces + ipi - descontos

        # Escolha MVA x MULT (sua regra atual)
        if usar_multiplicador and p.get("MULT", 0.0) > 0:
            perc = _f(p["MULT"])
            mva_tipo = "multiplicador_zfm"
        else:
            perc = _f(p.get("MVA", 0.0))
            mva_tipo = "mva_percentual"

        fator = 1.0 + (perc / 100.0)  # fator multiplicador (ex.: 1.50 para 50%)

        # Valor Agregado e Base ST
        valor_agregado = valor_operacao * (fator - 1.0)
        base_st = valor_operacao * fator

        # Alíquota ICMS-ST (usamos ALI_INT como “alíquota destino”)
        aliq_st = _f(p.get("ALI_INT", 0.18))  # decimal

        # ICMS teórico do destino
        icms_teorico_dest = base_st * aliq_st

        # ICMS origem (interestadual) “de abatimento” (modelo encerramento)
        ali_inter = _f(p.get("ALI_INTER", 0.12))
        icms_origem_calc = valor_operacao * ali_inter

        # Crédito presumido (se você já usa — senão isso fica 0)
        cred_perc = _f(p.get("CRED_PERC", 0.0))
        cred_tipo = str(p.get("CRED_TIPO", "SOBRE_DEBITO")).upper()
        if cred_perc > 0:
            credito_presumido = (icms_teorico_dest * cred_perc) if cred_tipo == "SOBRE_DEBITO" else (
                        base_st * cred_perc)
        else:
            credito_presumido = 0.0

        # ICMS-ST devido (modelo encerramento “padrão”)
        icms_st = icms_teorico_dest - icms_origem_calc - icms_dest_origem - credito_presumido - icms_desonerado
        if icms_st < 0:
            icms_st = 0.0

        # --------- Preenche a memória com os NOMES que você quer na tela ----------
        memoria.update({
            "SEQUENCIAL ITEM": sequencial_item,
            "COD. PRODUTO": cod_produto,
            "DESCRIÇÃO": descricao,
            "NCM": ncm,
            "QUANT.": quant,
            "VALOR UNIT.": valor_unit,
            "VLR TOTAL PRODUTO.": vlr_total_prod,
            "FRETE": frete,
            "IPI": ipi,
            "DESP. ACES.": desp_aces,
            "ICMS DESONERADO": icms_desonerado,
            "VALOR DA VENDA COM DESCONTO DE ICMS": valor_venda_com_desc_icms,
            "VALOR DA OPERAÇÃO": valor_operacao,
            "MARGEM DE VALOR AGREGADO - MVA": perc,  # em %
            "VALOR AGREGADO": valor_agregado,
            "BASE DE CÁLCULO SUBSTITUIÇÃO TRIBUTÁRIA": base_st,
            "ALÍQUOTA ICMS-ST": aliq_st,  # decimal (exibir como % na view)
            "VALOR DO ICMS ST": icms_st,
            "VALOR SALDO DEVEDOR ICMS ST": icms_st,
            "MULTIPLICADOR SEFAZ": fator,  # fator (ex.: 1.50)
            "VALOR ICMS RETIDO": icms_st,

            # extras úteis para auditoria
            "mva_tipo": mva_tipo,
            "icms_teorico_dest": icms_teorico_dest,
            "icms_origem_calc": icms_origem_calc,
            "credito_presumido": credito_presumido,
        })

        return ResultadoItem(
            base_calculo_st=base_st,
            icms_st_devido=icms_st,
            memoria=memoria
        )
