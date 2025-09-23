# xml_parser.py
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import xml.etree.ElementTree as ET

# -----------------------------------------------------------------------------
# Modelo de item: inclui nomes "duplicados" para compatibilidade com seu calc.py
# e para exibir exatamente os campos que você quer na tabela.
# -----------------------------------------------------------------------------
@dataclass
class ItemNF:
    # Identificação
    nItem: int
    cProd: str
    xProd: str
    ncm: str
    cfop: str
    cst: str  # CST ou CSOSN (o que existir)

    # Quantidade / valores por item
    qCom: float
    vUnCom: float

    # Totais do item (nomenclaturas compatíveis)
    vProd: float                 # valor total do produto no item
    valor_produto: float         # alias de vProd

    vFrete: float                # frete informado no item (se vier)
    frete_rateado: float         # alias de vFrete (ou 0.0 se não vier)

    vOutro: float                # despesas acessórias do item
    despesas_acessorias: float   # alias

    vDesc: float                 # desconto do item
    descontos: float             # alias

    vIPI: float                  # IPI do item (se houver)
    ipi: float                   # alias

    # ICMS destacado e desoneração
    vICMS: float                 # ICMS destacado do item (se houver)
    icms_destacado_origem: float # alias

    vICMSDeson: float            # ICMS desonerado (se houver)
    icms_desonerado: float       # alias

    motDesICMS: str              # motivo da desoneração (se houver)

class NFEXML:
    def __init__(self, xml_bytes: bytes):
        # Algumas NF-e usam ns diferentes; { * } nas buscas abaixa o namespace.
        self.root = ET.fromstring(xml_bytes)

    # Helper para buscar nós com namespace “curinga”
    def _find(self, path: str) -> Optional[ET.Element]:
        return self.root.find(f".//{{*}}{path}")

    def _findall(self, path: str) -> List[ET.Element]:
        return self.root.findall(f".//{{*}}{path}")

    def _txtf(self, el: Optional[ET.Element], path: str, default: float = 0.0) -> float:
        try:
            txt = (el.findtext(f".//{{*}}{path}") if el is not None else None) or ""
            txt = txt.strip().replace(",", ".")
            return float(txt) if txt else default
        except Exception:
            return default

    def _txt(self, el: Optional[ET.Element], path: str, default: str = "") -> str:
        try:
            txt = (el.findtext(f".//{{*}}{path}") if el is not None else None)
            return (txt or default).strip()
        except Exception:
            return default

    def header(self) -> Dict[str, Any]:
        emit = self._find("emit")
        dest = self._find("dest")
        uf_origem = self._txt(emit, "UF", "").upper()
        uf_destino = self._txt(dest, "UF", "").upper()
        return {"uf_origem": uf_origem, "uf_destino": uf_destino}

    def itens(self) -> List[ItemNF]:
        out: List[ItemNF] = []

        # Em muitas NF-e o frete não vem por item; vem no total (total/vNF/vFrete).
        # Aqui buscamos apenas o que estiver no item (prod.vFrete). Se vier vazio, fica 0.0
        for det in self._findall("det"):
            prod = det.find(".//{*}prod")
            imposto = det.find(".//{*}imposto")

            nItem = int(det.attrib.get("nItem", "0") or 0)
            cProd = self._txt(prod, "cProd")
            xProd = self._txt(prod, "xProd")
            ncm   = self._txt(prod, "NCM")
            cfop  = self._txt(prod, "CFOP")

            # CST / CSOSN
            cst = ""
            icms_node = None
            if imposto is not None:
                # Existem vários grupos: ICMS00, ICMS20, ICMS10, ICMS40, ICMS60, CSOSNxxx etc.
                # Pegamos o primeiro grupo ICMS* existente.
                for child in imposto.findall(".//{*}ICMS/*"):
                    icms_node = child
                    break
            if icms_node is not None:
                cst = (icms_node.findtext(".//{*}CST") or icms_node.findtext(".//{*}CSOSN") or "").strip()

            # Quantidades e valores
            def fnum(tag: str, default: float = 0.0) -> float:
                return self._txtf(prod, tag, default)

            qCom   = fnum("qCom")
            vUnCom = fnum("vUnCom")
            vProd  = fnum("vProd")
            vFrete = fnum("vFrete")          # pode ser 0 na maioria dos casos
            vOutro = fnum("vOutro")
            vDesc  = fnum("vDesc")

            # IPI (se houver)
            vIPI = 0.0
            if imposto is not None:
                vIPI = self._txtf(imposto, "IPI/vIPI", 0.0)

            # ICMS destacado
            vICMS = 0.0
            if imposto is not None:
                # vICMS costuma estar dentro do subgrupo do ICMS daquele item
                # Ex.: imposto/ICMS/ICMS20/vICMS
                vICMS_el = imposto.find(".//{*}ICMS//{*}vICMS")
                if vICMS_el is not None:
                    try:
                        vICMS = float(vICMS_el.text.strip().replace(",", "."))
                    except Exception:
                        vICMS = 0.0

            # ICMS desonerado e motivo
            vICMSDeson = 0.0
            motDesICMS = ""
            if imposto is not None:
                vICMSDeson = self._txtf(imposto, "ICMS//vICMSDeson", 0.0)
                motDesICMS = self._txt(imposto, "ICMS//motDesICMS", "")

            # Construção do Item com aliases para manter compatibilidade
            out.append(ItemNF(
                nItem=nItem,
                cProd=cProd,
                xProd=xProd,
                ncm=ncm,
                cfop=cfop,
                cst=cst,

                qCom=qCom,
                vUnCom=vUnCom,

                vProd=vProd,
                valor_produto=vProd,         # alias

                vFrete=vFrete,
                frete_rateado=vFrete,        # alias (se vFrete=0, fica 0; pode ser rateado depois)

                vOutro=vOutro,
                despesas_acessorias=vOutro,  # alias

                vDesc=vDesc,
                descontos=vDesc,             # alias

                vIPI=vIPI,
                ipi=vIPI,                    # alias

                vICMS=vICMS,
                icms_destacado_origem=vICMS, # alias

                vICMSDeson=vICMSDeson,
                icms_desonerado=vICMSDeson,  # alias

                motDesICMS=motDesICMS,
            ))

        return out
