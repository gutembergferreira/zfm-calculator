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

    # calc.py — dentro da classe MotorCalculo
    # (mantém o resto do arquivo igual; apenas substitua este método)

    def calcula_st(self, item: "ItemNF", uf_origem: str, uf_destino: str,
                   usar_multiplicador: bool = True) -> "ResultadoItem":
        p = self._busca_param(item.ncm, uf_origem, uf_destino)

        memoria = {"parametros": p}

        # --- entradas do item (com fallback pros nomes que já existem no seu modelo) ---
        def _f(x, d=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return d

        seq = int(getattr(item, "nItem", 0))
        cprod = getattr(item, "cProd", "")
        xprod = getattr(item, "xProd", "")
        ncm = getattr(item, "ncm", "")
        cfop = getattr(item, "cfop", "")
        cst = getattr(item, "cst", "")
        quant = _f(getattr(item, "qCom", 0.0))
        vun = _f(getattr(item, "vUnCom", 0.0))

        vprod = _f(getattr(item, "vProd", getattr(item, "valor_produto", 0.0)))
        vfrete = _f(getattr(item, "vFrete", getattr(item, "frete_rateado", 0.0)))
        vout = _f(getattr(item, "vOutro", getattr(item, "despesas_acessorias", 0.0)))
        vdesc = _f(getattr(item, "vDesc", getattr(item, "descontos", 0.0)))
        vipi = _f(getattr(item, "vIPI", getattr(item, "ipi", 0.0)))
        vdeson = _f(getattr(item, "vICMSDeson", getattr(item, "icms_desonerado", 0.0)))
        vicms_origem_destacado = _f(getattr(item, "vICMS", getattr(item, "icms_destacado_origem", 0.0)))

        # --- valor da operação padrão ---
        valor_oper_sem_desc = vprod + vfrete + vout + vipi - vdesc

        # --- conforme sua planilha: desconta o ICMS desonerado da base da MVA ---
        valor_venda_desc_icms = valor_oper_sem_desc - vdeson
        if valor_venda_desc_icms < 0:
            valor_venda_desc_icms = 0.0

        # --- MVA x Multiplicador (para formação da base ST) ---
        # p["MVA"] vem como % (ex.: 35 -> 35%). Se vier fracionário (0.35), converta antes na _busca_param.
        if usar_multiplicador and _f(p.get("MULT", 0.0)) > 0:
            perc_mva = _f(p["MULT"])
            mva_tipo = "multiplicador_zfm"
        else:
            perc_mva = _f(p.get("MVA", 0.0))
            mva_tipo = "mva_percentual"

        fator_mva = 1.0 + (perc_mva / 100.0)
        valor_agregado = valor_venda_desc_icms * (fator_mva - 1.0)
        base_st = valor_venda_desc_icms * fator_mva

        # --- alíquotas ---
        aliq_dest = _f(p.get("ALI_INT", 0.18))  # decimal
        aliq_inter = _f(p.get("ALI_INTER", 0.12))

        # --- ICMS teórico do destino ---
        icms_teorico_dest = base_st * aliq_dest

        # --- ICMS de origem (abatimento) ---
        # regra da planilha: usa "Multiplicador SEFAZ" se existir; senão cai pra ALI_INTER
        mult_sefaz = _f(p.get("MULT_SEFAZ", p.get("MULT_ORIGEM", 0.0)))
        if mult_sefaz > 0:
            icms_origem_calc = valor_venda_desc_icms * mult_sefaz  # mult_sefaz já deve vir decimal (ex.: 0.1947)
            mult_exibicao = mult_sefaz
        else:
            icms_origem_calc = valor_venda_desc_icms * aliq_inter
            mult_exibicao = aliq_inter

        # --- crédito presumido (se houver política ativa) ---
        cred_perc = _f(p.get("CRED_PERC", 0.0))  # decimal
        cred_tipo = str(p.get("CRED_TIPO", "SOBRE_DEBITO")).upper()
        if cred_perc > 0:
            credito_presumido = (icms_teorico_dest * cred_perc) if cred_tipo == "SOBRE_DEBITO" else (
                        base_st * cred_perc)
        else:
            credito_presumido = 0.0

        # --- ICMS-ST devido ---
        icms_st = icms_teorico_dest - icms_origem_calc - vicms_origem_destacado - credito_presumido
        # (o ICMS desonerado foi tirado da base; não subtrai novamente aqui)
        if icms_st < 0:
            icms_st = 0.0

        # --- memória com os nomes idênticos aos da sua planilha/tela ---
        memoria.update({
            "SEQUENCIAL ITEM": seq,
            "COD. PRODUTO": cprod,
            "DESCRIÇÃO": xprod,
            "NCM": ncm,
            "QUANT.": quant,
            "VALOR UNIT.": vun,
            "VLR TOTAL PRODUTO.": vprod,
            "FRETE": vfrete,
            "IPI": vipi,
            "DESP. ACES.": vout,
            "ICMS DESONERADO": vdeson,
            "VALOR DA VENDA COM DESCONTO DE ICMS": valor_venda_desc_icms,
            "VALOR DA OPERAÇÃO": valor_venda_desc_icms,  # sua planilha mostra ambos iguais
            "MARGEM DE VALOR AGREGADO - MVA": perc_mva,  # em %
            "VALOR AGREGADO": valor_agregado,
            "BASE DE CÁLCULO SUBSTITUIÇÃO TRIBUTÁRIA": base_st,
            "ALÍQUOTA ICMS-ST": aliq_dest,  # decimal
            "VALOR DO ICMS ST": icms_st,
            "VALOR SALDO DEVEDOR ICMS ST": icms_st,
            "MULTIPLICADOR SEFAZ": mult_exibicao,  # decimal (ex.: 0.1947)
            "VALOR ICMS RETIDO": icms_st,

            "mva_tipo": mva_tipo,
            "icms_teorico_dest": icms_teorico_dest,
            "icms_origem_calc": icms_origem_calc,
            "credito_presumido": credito_presumido,
            "cfop": cfop,
            "cst": cst,
        })

        return ResultadoItem(
            base_calculo_st=base_st,
            icms_st_devido=icms_st,
            memoria=memoria
        )

