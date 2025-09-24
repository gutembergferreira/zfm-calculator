# calc.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, getcontext, ROUND_HALF_UP
from typing import Dict, Any, List, Optional, Tuple

# opcional (o projeto já usa pandas)
try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None  # fallback p/ não quebrar import

# Precisão alta; arredondar só no fim
getcontext().prec = 28
ROUND = ROUND_HALF_UP

def D(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if x is None:
        return Decimal('0')
    if isinstance(x, (int, float)):
        return Decimal(str(x))
    s = str(x).strip()
    # aceita "1.234,56" e "1234,56"
    if '.' in s and ',' in s and s.rfind(',') > s.rfind('.'):
        s = s.replace('.', '').replace(',', '.')
    else:
        s = s.replace(',', '.')
    try:
        return Decimal(s or '0')
    except Exception:
        return Decimal('0')

def q2(x) -> Decimal:
    return D(x).quantize(Decimal('0.01'), rounding=ROUND)

def pct(x) -> Decimal:
    v = D(x)
    return v/Decimal(100) if v > 1 else v

# ---------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------
@dataclass
class ItemNF:
    ncm: str = ""
    cfop: str = ""
    cst: str = ""
    quantidade: Decimal = Decimal('0')
    valor_unitario: Decimal = Decimal('0')
    frete: Decimal = Decimal('0')
    ipi: Decimal = Decimal('0')
    despesas_acessorias: Decimal = Decimal('0')
    descontos: Decimal = Decimal('0')
    icms_destacado_origem: Decimal = Decimal('0')
    icms_desonerado: Decimal = Decimal('0')
    motivo_desoneracao: str = ""
    incluir_frete_no_desonerado: bool = True
    incluir_despesas_no_desonerado: bool = True
    # eco
    cod_produto: str = ""
    descricao: str = ""

@dataclass
class ResultadoItem:
    base_calculo_st: Decimal
    icms_st_devido: Decimal
    memoria: Dict[str, Any]

# ---------------------------------------------------------------------
# Motor de cálculo
# ---------------------------------------------------------------------
class MotorCalculo:
    """
    Motor com consulta a 'matrices' (Google Sheets). Aplique ST só quando:
      - houver regra explícita para o NCM/UF (APLICA_ST = True, ou existir MVA/ALI_INT),
      - caso contrário, NÃO aplica ST (zera MVA, base ST= venda_desc, alíquota interna=0).
    """
    def __init__(
        self,
        matrices: Optional[Dict[str, Any]] = None,
        aliquota_origem: Decimal = Decimal('0.07'),      # 7% origem (desoneração)
        mva: Decimal = Decimal('0.35'),                  # 35% default (se não houver planilha)
        aliquota_interna: Decimal = Decimal('0.20'),     # 20% default
        multiplicador_sefaz: Decimal = Decimal('0.1947') # 19,47% default
    ):
        self.matrices = matrices or {}
        self.aliquota_origem = D(aliquota_origem)
        self.mva_default = D(mva)
        self.aliquota_interna_default = D(aliquota_interna)
        self.multiplicador_sefaz_default = D(multiplicador_sefaz)

    # ------------------------- helpers matrices -------------------------

    @staticmethod
    def _norm(s: Any) -> str:
        return (str(s) if s is not None else "").strip().upper()

    @staticmethod
    def _only_digits(s: Any) -> str:
        return "".join(ch for ch in str(s) if ch.isdigit())

    @staticmethod
    def _to_bool(v: Any) -> Optional[bool]:
        if v is None: return None
        s = str(v).strip().upper()
        if s in ("1","TRUE","T","SIM","S","Y","YES","OK","ATIVO","APLICA"):
            return True
        if s in ("0","FALSE","F","NAO","N","NO","INATIVO","NAO APLICA","N/A","NA"):
            return False
        return None  # valor não interpretável

    @staticmethod
    def _first_present(row: Dict[str, Any], keys: List[str]) -> Optional[Any]:
        for k in keys:
            if k in row and row[k] not in (None, ""):
                return row[k]
        return None

    def _iter_dataframes(self):
        if not self.matrices:
            return
        for name, df in self.matrices.items():
            # aceita apenas DataFrame-like
            if pd is not None and isinstance(df, pd.DataFrame):
                yield name, df

    def _lookup_ncm_rules(self, ncm: str, uf_dest: str) -> Dict[str, Any]:
        """
        Procura nas planilhas qualquer linha para o NCM (match exato ou por prefixo) e UF de destino.
        Retorna:
          {
            'aplica_st': True/False/None,
            'mva': Decimal|None,
            'aliquota_interna': Decimal|None,
            'multiplicador': Decimal|None,
            'fonte': 'nome_da_aba'
          }
        Se nada encontrado, retorna dict vazio -> significa "sem regra".
        """
        ncm_digits = self._only_digits(ncm)
        uf = self._norm(uf_dest)

        melhor: Tuple[int, Dict[str, Any]] = ( -1, {} )  # (tamanho_do_prefixo_casado, regra)

        for name, df in self._iter_dataframes():
            if df is None or df.empty:
                continue
            # normaliza colunas
            cols_up = { self._norm(c): c for c in df.columns }

            # precisar ter pelo menos uma coluna de NCM
            col_ncm = None
            for candidate in ["NCM","NCM_RAIZ","NCM BASE","NCMBASE","COD_NCM","CODIGO NCM"]:
                if candidate in cols_up:
                    col_ncm = cols_up[candidate]
                    break
            if not col_ncm:
                continue

            # UF (se houver)
            col_uf = None
            for cuf in ["UF","UF_DESTINO","UF DEST","UF_DEST","DESTINO","UF_UF"]:
                if cuf in cols_up:
                    col_uf = cols_up[cuf]
                    break

            # colunas possíveis de decisão
            # aplica ST?
            cand_aplica = [k for k in ["APLICA_ST","APLICA SUBSTITUICAO","APLICA SUBSTITUIÇÃO","ST","TEM_ST","ST_ATIVO","SUBSTITUICAO","SUBSTITUIÇÃO"] if k in cols_up]
            cand_mva = [k for k in ["MVA","MVA %","MVA_PERCENTUAL","MVA_PERC","MARGEM","MARGEM (%)","MARGEM_DE_VALOR_AGREGADO_MVA"] if k in cols_up]
            cand_ali = [k for k in ["ALI_INT","ALIQ_INT","ALIQUOTA_INTERNA","ALIQ INTERNA","ALÍQUOTA INTERNA","ALÍQUOTA ICMS","ALIQUOTA ICMS"] if k in cols_up]
            cand_mult = [k for k in ["MULT_SEFAZ","MULTIPLICADOR","MULT","ALI_INTER","ALIQUOTA_INTER"] if k in cols_up]

            # varremos linhas com NCM compatível
            for _, row in df.iterrows():
                raw_ncm = self._only_digits(row[col_ncm])
                if not raw_ncm:
                    continue
                # match por prefixo: o mais específico (maior len) ganha
                if not ncm_digits.startswith(raw_ncm):
                    continue

                # checa UF (se existir coluna UF, deve bater; senão, aceita geral)
                if col_uf:
                    uf_row = self._norm(row[col_uf])
                    if uf_row and uf_row not in ("", uf, "TODAS", "TODOS", "ALL", "*"):
                        continue

                # coleta valores
                aplica_st = self._to_bool(self._first_present(row, [cols_up[k] for k in cand_aplica])) if cand_aplica else None
                mva_val = self._first_present(row, [cols_up[k] for k in cand_mva]) if cand_mva else None
                ali_val = self._first_present(row, [cols_up[k] for k in cand_ali]) if cand_ali else None
                mult_val = self._first_present(row, [cols_up[k] for k in cand_mult]) if cand_mult else None

                regra = {
                    "aplica_st": aplica_st,
                    "mva": (pct(mva_val) if mva_val not in (None, "") else None),
                    "aliquota_interna": (pct(ali_val) if ali_val not in (None, "") else None),
                    "multiplicador": (pct(mult_val) if mult_val not in (None, "") else None),
                    "fonte": name,
                    "ncm_match": raw_ncm,
                }

                # escolhe a mais específica
                prefix_len = len(raw_ncm)
                if prefix_len > melhor[0]:
                    melhor = (prefix_len, regra)

        return melhor[1]

    # ------------------------- núcleo de cálculo -------------------------

    def _params_item(self, raw: Dict[str, Any]) -> Dict[str, Decimal]:
        return {
            "aliq_origem": pct(raw.get("aliquota_origem", self.aliquota_origem)),
            "mva":         pct(raw.get("mva", self.mva_default)),
            "aliq_interna":pct(raw.get("aliquota_interna", self.aliquota_interna_default)),
            "mult_sefaz":  pct(raw.get("multiplicador_sefaz", self.multiplicador_sefaz_default)),
            "incl_frete":  bool(raw.get("incluir_frete_no_desonerado", True)),
            "incl_desp":   bool(raw.get("incluir_despesas_no_desonerado", True)),
        }

    def _calcular_com_param(self, it: ItemNF, p: Dict[str, Decimal]) -> Dict[str, Any]:
        qtd = D(it.quantidade)
        vu  = D(it.valor_unitario)
        vlr_prod = q2(qtd * vu)

        frete = D(it.frete)
        desp  = D(it.despesas_acessorias)
        ipi   = D(it.ipi)  # fora da base neste cenário

        # 1) Base da operação (produto + frete + despesas)
        base_oper = vlr_prod + frete + desp

        # 2) ICMS desonerado — inclui frete/desp (CIF) conforme flags
        base_des = vlr_prod
        if p["incl_frete"]:
            base_des += frete
        if p["incl_desp"]:
            base_des += desp
        icms_des = q2(p["aliq_origem"] * base_des)

        # 3) Venda com desconto
        venda_desc = q2(base_oper - icms_des)

        # 4) MVA sobre venda_desc
        valor_agregado = q2(p["mva"] * venda_desc)

        # 5) Base ST
        base_st = q2(venda_desc + valor_agregado)

        # 6) ICMS teórico destino
        icms_teorico_dest = q2(p["aliq_interna"] * base_st)

        # 7) ICMS origem calculado
        icms_origem_calc = icms_des

        # 8) Valor do ICMS ST (teórico)
        icms_st = icms_teorico_dest

        # 9) Saldo
        saldo_devedor = q2(icms_teorico_dest - icms_origem_calc)

        # 10) Multiplicador SEFAZ e ICMS retido (não arredondar o multiplicador)
        mult_sefaz = p["mult_sefaz"]
        icms_retido = q2(mult_sefaz * venda_desc)

        return {
            "base_oper": base_oper,
            "venda_desc": venda_desc,
            "valor_agregado": valor_agregado,
            "base_st": base_st,
            "icms_teorico_dest": icms_teorico_dest,
            "icms_origem_calc": icms_origem_calc,
            "icms_st": icms_st,
            "saldo_devedor": saldo_devedor,
            "mult_sefaz": mult_sefaz,
            "icms_retido": icms_retido,
            "icms_des": icms_des,
        }

    def calcular_linha(self, it: ItemNF, raw: Dict[str, Any]) -> Dict[str, Any]:
        p = self._params_item(raw)
        r = self._calcular_com_param(it, p)

        # saída formatada
        return {
            "cod_produto": it.cod_produto or "",
            "descricao": it.descricao or "",
            "ncm": it.ncm or "",
            "cst": it.cst or "",
            "cfop": it.cfop or "",
            "quantidade": float(q2(it.quantidade)),
            "valor_unitario": float(q2(it.valor_unitario)),
            "valor_total_produto": float(q2(it.quantidade * it.valor_unitario)),
            "frete": float(q2(it.frete)),
            "ipi": float(q2(it.ipi)),
            "desp_acessoria": float(q2(it.despesas_acessorias)),

            "icms_deson": float(r["icms_des"]),
            "venda_desc_icms": float(r["venda_desc"]),
            "valor_oper": float(r["venda_desc"]),

            "mva_tipo": "MVA Padrão",
            "mva_percent": float(q2(p["mva"] * 100)),
            "valor_agregado": float(r["valor_agregado"]),
            "base_st": float(r["base_st"]),

            "aliq_st": float(p["aliq_interna"]),  # fração
            "icms_teorico_dest": float(r["icms_teorico_dest"]),
            "icms_origem_calc": float(r["icms_origem_calc"]),
            "icms_st": float(r["icms_st"]),
            "saldo_devedor": float(r["saldo_devedor"]),

            "mult_sefaz": float(r["mult_sefaz"]),  # fração
            "icms_retido": float(r["icms_retido"]),

            "memoria": {
                "base_oper": r["base_oper"],
                "base_desonerado": q2(D(it.quantidade)*D(it.valor_unitario)) + (D(it.frete) if p["incl_frete"] else 0) + (D(it.despesas_acessorias) if p["incl_desp"] else 0),
                "aliq_origem": p["aliq_origem"],
                "aliq_interna": p["aliq_interna"],
                "mva": p["mva"],
                "mult_sefaz": r["mult_sefaz"],
            },
        }

    def calcular(self, itens: List[Dict[str, Any]], defaults: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        linhas = []
        defaults = defaults or {}
        for raw in itens:
            it = ItemNF(
                ncm = str(raw.get("ncm", "")),
                cfop = str(raw.get("cfop", "")),
                cst = str(raw.get("cst", "")),
                quantidade = D(raw.get("quantidade", 0)),
                valor_unitario = D(raw.get("valor_unitario", 0)),
                frete = D(raw.get("frete", 0)),
                ipi = D(raw.get("ipi", 0)),
                despesas_acessorias = D(raw.get("desp_acessoria", raw.get("despesas_acessorias", 0))),
                descontos = D(raw.get("descontos", 0)),
                icms_destacado_origem = D(raw.get("icms_destacado_origem", 0)),
                icms_desonerado = D(raw.get("icms_desonerado", 0)),
                motivo_desoneracao = str(raw.get("motivo_desoneracao", "")),
                incluir_frete_no_desonerado = bool(raw.get("incluir_frete_no_desonerado", True)),
                incluir_despesas_no_desonerado = bool(raw.get("incluir_despesas_no_desonerado", True)),
                cod_produto = str(raw.get("cod_produto", raw.get("cProd", ""))),
                descricao = str(raw.get("descricao", raw.get("xProd", ""))),
            )
            merged = {**defaults, **raw}
            linha = self.calcular_linha(it, merged)
            linhas.append(linha)
        return linhas

    # Compatível com app.py
    def calcula_st(self, nf_item: Any, uf_origem: str, uf_destino: str, usar_multiplicador: bool = True) -> ResultadoItem:
        """
        Consulta planilhas p/ decidir se aplica ST; se não aplicar, zera ST.
        """
        # monta item interno
        it = ItemNF(
            ncm=str(getattr(nf_item, "ncm", "") or ""),
            cfop=str(getattr(nf_item, "cfop", "") or ""),
            cst=str(getattr(nf_item, "cst", "") or ""),
            quantidade=D(getattr(nf_item, "qCom", 0)),
            valor_unitario=D(getattr(nf_item, "vUnCom", 0)),
            frete=D(getattr(nf_item, "vFrete", 0)),
            ipi=D(getattr(nf_item, "vIPI", 0)),
            despesas_acessorias=D(getattr(nf_item, "vOutro", 0)),
            descontos=D(0),
            icms_destacado_origem=D(0),
            icms_desonerado=D(getattr(nf_item, "vICMSDeson", 0)),
            incluir_frete_no_desonerado=True,
            incluir_despesas_no_desonerado=True,
            cod_produto=str(getattr(nf_item, "cProd", "") or ""),
            descricao=str(getattr(nf_item, "xProd", "") or "")
        )

        # consulta regras por NCM/UF
        regra = self._lookup_ncm_rules(it.ncm, uf_destino)

        # começa com defaults
        p_raw: Dict[str, Any] = {
            "aliquota_origem": self.aliquota_origem,
            "mva": self.mva_default,
            "aliquota_interna": self.aliquota_interna_default,
            "multiplicador_sefaz": (self.multiplicador_sefaz_default if usar_multiplicador else Decimal('0')),
            "incluir_frete_no_desonerado": True,
            "incluir_despesas_no_desonerado": True,
        }

        aplica_st: Optional[bool] = None
        if regra:
            # se a planilha disser explicitamente que NÃO aplica, respeita
            if regra.get("aplica_st") is False:
                aplica_st = False
            # se houver parâmetros numéricos na linha, considera que aplica
            if regra.get("aplica_st") is True or any(regra.get(k) is not None for k in ("mva","aliquota_interna","multiplicador")):
                aplica_st = True

            if regra.get("mva") is not None:
                p_raw["mva"] = regra["mva"]
            if regra.get("aliquota_interna") is not None:
                p_raw["aliquota_interna"] = regra["aliquota_interna"]
            if regra.get("multiplicador") is not None:
                p_raw["multiplicador_sefaz"] = (regra["multiplicador"] if usar_multiplicador else Decimal('0'))

        # se não achou regra, comportamento conservador: NÃO aplica ST
        if aplica_st is not True:
            # calcula venda_desc/oper/desoneração normalmente,
            # mas zera MVA/aliquota interna/multiplicador para não gerar ST
            p_raw_no_st = dict(p_raw)
            p_raw_no_st["mva"] = Decimal('0')
            p_raw_no_st["aliquota_interna"] = Decimal('0')
            p_raw_no_st["multiplicador_sefaz"] = Decimal('0')

            # calcula
            p_no = self._params_item(p_raw_no_st)
            r = self._calcular_com_param(it, p_no)

            # monta memória/resultado zerado de ST
            memoria: Dict[str, Any] = {
                "SEQUENCIAL ITEM": str(getattr(nf_item, "nItem", "")),
                "COD. PRODUTO": it.cod_produto,
                "DESCRIÇÃO": it.descricao,
                "NCM": it.ncm,

                "QUANT.": float(q2(it.quantidade)),
                "VALOR UNIT.": float(q2(it.valor_unitario)),
                "VLR TOTAL PRODUTO.": float(q2(it.quantidade*it.valor_unitario)),
                "FRETE": float(q2(it.frete)),
                "IPI": float(q2(it.ipi)),
                "DESP. ACES.": float(q2(it.despesas_acessorias)),
                "ICMS DESONERADO": float(r["icms_des"]),

                "VALOR DA VENDA COM DESCONTO DE ICMS": float(r["venda_desc"]),
                "VALOR DA OPERAÇÃO": float(r["venda_desc"]),

                "mva_tipo": "Sem ST",
                "MARGEM DE VALOR AGREGADO - MVA": 0.0,
                "MARGEM_DE_VALOR_AGREGADO_MVA": 0.0,
                "VALOR AGREGADO": 0.0,
                "VALOR_AGREGADO": 0.0,

                "BASE DE CÁLCULO SUBSTITUIÇÃO TRIBUTÁRIA": float(r["venda_desc"]),  # mostra a venda p/ transparência
                "BASE_ST": float(r["venda_desc"]),

                "ALÍQUOTA ICMS-ST": 0.0,
                "icms_teorico_dest": 0.0,
                "icms_origem_calc": float(r["icms_des"]),
                "VALOR DO ICMS ST": 0.0,
                "VALOR_ICMS_ST": 0.0,

                "VALOR SALDO DEVEDOR ICMS ST": 0.0,
                "SALDO_DEVEDOR_ST": 0.0,

                "MULTIPLICADOR SEFAZ": 0.0,
                "MULT_SEFAZ": 0.0,

                "VALOR ICMS RETIDO": 0.0,

                "parametros": {
                    "ALI_INT": 0.0,
                    "ALI_INTER": 0.0,
                    "UF_ORIGEM": uf_origem,
                    "UF_DESTINO": uf_destino,
                    "APLICA_ST": False,
                    "FONTE_REGRAS": regra.get("fonte") if regra else None,
                },
                "venda_desc_icms": float(r["venda_desc"]),
            }

            return ResultadoItem(
                base_calculo_st=Decimal(str(r["venda_desc"])),
                icms_st_devido=Decimal('0'),
                memoria=memoria
            )

        # aplica ST normalmente com os parâmetros (regra/defaut)
        p_use = self._params_item(p_raw)
        r = self._calcular_com_param(it, p_use)

        memoria: Dict[str, Any] = {
            "SEQUENCIAL ITEM": str(getattr(nf_item, "nItem", "")),
            "COD. PRODUTO": it.cod_produto,
            "DESCRIÇÃO": it.descricao,
            "NCM": it.ncm,

            "QUANT.": float(q2(it.quantidade)),
            "VALOR UNIT.": float(q2(it.valor_unitario)),
            "VLR TOTAL PRODUTO.": float(q2(it.quantidade*it.valor_unituario if hasattr(it,'valor_unituario') else it.valor_unitario)),
            "FRETE": float(q2(it.frete)),
            "IPI": float(q2(it.ipi)),
            "DESP. ACES.": float(q2(it.despesas_acessorias)),
            "ICMS DESONERADO": float(r["icms_des"]),

            "VALOR DA VENDA COM DESCONTO DE ICMS": float(r["venda_desc"]),
            "VALOR DA OPERAÇÃO": float(r["venda_desc"]),

            "mva_tipo": "MVA Padrão",
            "MARGEM DE VALOR AGREGADO - MVA": float(q2(p_use["mva"] * 100)),
            "MARGEM_DE_VALOR_AGREGADO_MVA": float(q2(p_use["mva"] * 100)),
            "VALOR AGREGADO": float(r["valor_agregado"]),
            "VALOR_AGREGADO": float(r["valor_agregado"]),

            "BASE DE CÁLCULO SUBSTITUIÇÃO TRIBUTÁRIA": float(r["base_st"]),
            "BASE_ST": float(r["base_st"]),

            "ALÍQUOTA ICMS-ST": float(p_use["aliq_interna"]),
            "icms_teorico_dest": float(r["icms_teorico_dest"]),
            "icms_origem_calc": float(r["icms_origem_calc"]),
            "VALOR DO ICMS ST": float(r["icms_st"]),
            "VALOR_ICMS_ST": float(r["icms_st"]),

            "VALOR SALDO DEVEDOR ICMS ST": float(r["saldo_devedor"]),
            "SALDO_DEVEDOR_ST": float(r["saldo_devedor"]),

            "MULTIPLICADOR SEFAZ": float(p_use["mult_sefaz"]),
            "MULT_SEFAZ": float(p_use["mult_sefaz"]),

            "VALOR ICMS RETIDO": float(r["icms_retido"]),

            "parametros": {
                "ALI_INT": float(p_use["aliq_interna"]),
                "ALI_INTER": float(p_use["mult_sefaz"]),
                "UF_ORIGEM": uf_origem,
                "UF_DESTINO": uf_destino,
                "APLICA_ST": True,
                "FONTE_REGRAS": regra.get("fonte") if regra else None,
            },
            "venda_desc_icms": float(r["venda_desc"]),
        }

        return ResultadoItem(
            base_calculo_st=Decimal(str(r["base_st"])),
            icms_st_devido=Decimal(str(r["icms_st"])),
            memoria=memoria
        )
