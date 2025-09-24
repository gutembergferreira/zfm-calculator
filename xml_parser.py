# xml_parser.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

getcontext().prec = 28
ROUND = ROUND_HALF_UP

def D(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if x is None:
        return Decimal("0")
    s = str(x).strip()
    if "." in s and "," in s and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s or "0")
    except Exception:
        return Decimal("0")

def q2(x) -> Decimal:
    return D(x).quantize(Decimal("0.01"), rounding=ROUND)

@dataclass
class NFItem:
    nItem: str
    cProd: str
    xProd: str
    ncm: str
    cst: str
    cfop: str

    qCom: Decimal
    vUnCom: Decimal
    vProd: Decimal

    vFrete: Decimal
    vIPI: Decimal
    vOutro: Decimal
    vICMSDeson: Decimal

    # campos adicionais para a prévia
    uCom: str = ""
    uTrib: str = ""
    cEAN: str = ""
    cEANTrib: str = ""
    cest: str = ""

class NFEXML:
    def __init__(self, xml_bytes: bytes):
        # funciona com <NFe> e <nfeProc>
        self.root = ET.fromstring(xml_bytes)

    # helpers de XPath com wildcard de namespace
    def _find(self, path: str) -> Optional[ET.Element]:
        return self.root.find(f".//{{*}}{path}")

    def _findall(self, path: str) -> List[ET.Element]:
        return self.root.findall(f".//{{*}}{path}")

    def _txt(self, el: Optional[ET.Element], path: str, default: str = "") -> str:
        try:
            val = el.findtext(f".//{{*}}{path}") if el is not None else None
            return (val or default).strip()
        except Exception:
            return default

    def _num(self, el: Optional[ET.Element], path: str, default: Decimal = Decimal("0")) -> Decimal:
        s = self._txt(el, path, "")
        return D(s) if s else default

    # ---------------------- Cabeçalho (achatado + blocos) ----------------------
    def header(self) -> Dict[str, Any]:
        ide   = self._find("ide")
        emit  = self._find("emit")
        dest  = self._find("dest")
        transp= self._find("transp")
        infNFe= self._find("infNFe")

        chave = infNFe.attrib.get("Id", "").replace("NFe", "") if infNFe is not None else ""

        # endereço formatado
        def fmt_addr(prefix: str) -> str:
            xLgr = self._txt(emit if "Emit" in prefix else dest, f"{prefix}/xLgr")
            nro  = self._txt(emit if "Emit" in prefix else dest, f"{prefix}/nro")
            bai  = self._txt(emit if "Emit" in prefix else dest, f"{prefix}/xBairro")
            parts = []
            if xLgr: parts.append(xLgr)
            if nro:  parts.append(nro)
            if bai:  parts.append(bai)
            return ", ".join(parts)

        head = {
            # achatado (o template usa estes)
            "chave": chave,
            "chNFe": chave,  # alias
            "numero": self._txt(ide, "nNF"),
            "serie":  self._txt(ide, "serie"),
            "modelo": self._txt(ide, "mod"),
            "natOp":  self._txt(ide, "natOp"),
            "dhEmi":  self._txt(ide, "dhEmi") or self._txt(ide, "dEmi"),
            "dhSaiEnt": self._txt(ide, "dhSaiEnt") or self._txt(ide, "dSaiEnt"),
            "emitente_nome": self._txt(emit, "xNome"),
            "emitente_cnpj": self._txt(emit, "CNPJ") or self._txt(emit, "CPF"),
            "emitente_ie":   self._txt(emit, "IE"),
            "emitente_endereco": fmt_addr("enderEmit"),
            "emitente_municipio": self._txt(emit, "enderEmit/xMun"),
            "emitente_uf":   self._txt(emit, "enderEmit/UF"),
            "emitente_cep":  self._txt(emit, "enderEmit/CEP"),
            "dest_nome": self._txt(dest, "xNome"),
            "dest_cnpj": self._txt(dest, "CNPJ") or self._txt(dest, "CPF"),
            "dest_ie":   self._txt(dest, "IE"),
            "dest_isuf": self._txt(dest, "ISUF"),
            "dest_endereco": fmt_addr("enderDest"),
            "dest_municipio": self._txt(dest, "enderDest/xMun"),
            "dest_uf":   self._txt(dest, "enderDest/UF"),
            "dest_cep":  self._txt(dest, "enderDest/CEP"),
            # UFs de movimentação para o formulário de cálculo
            "uf_origem":  self._txt(emit, "enderEmit/UF"),
            "uf_destino": self._txt(dest, "enderDest/UF"),
            # blocos originais (mantidos para compatibilidade)
            "ide": {
                "nNF":   self._txt(ide, "nNF"),
                "dhEmi": self._txt(ide, "dhEmi") or self._txt(ide, "dEmi"),
                "natOp": self._txt(ide, "natOp"),
                "mod":   self._txt(ide, "mod"),
                "serie": self._txt(ide, "serie"),
                "tpNF":  self._txt(ide, "tpNF"),
                "idDest":self._txt(ide, "idDest"),
            },
            "emit": {
                "xNome": self._txt(emit, "xNome"),
                "CNPJ":  self._txt(emit, "CNPJ"),
                "UF":    self._txt(emit, "enderEmit/UF"),
                "IE":    self._txt(emit, "IE"),
            },
            "dest": {
                "xNome": self._txt(dest, "xNome"),
                "CNPJ":  self._txt(dest, "CNPJ"),
                "UF":    self._txt(dest, "enderDest/UF"),
                "IE":    self._txt(dest, "IE"),
                "indIEDest": self._txt(dest, "indIEDest"),
            },
            "transp": {
                "modFrete": self._txt(transp, "modFrete"),
            }
        }
        return head

    # ------------------------------ Totais -------------------------------------
    def totais(self) -> Dict[str, float]:
        tot = self._find("total/ICMSTot")
        if tot is None:
            return {}
        keys = ["vProd","vFrete","vIPI","vDesc","vOutro","vST","vICMSDeson","vNF"]
        out: Dict[str, float] = {}
        for k in keys:
            out[k] = float(q2(self._num(tot, k, Decimal("0"))))
        return out

    # ---------------------------- Transporte -----------------------------------
    def transporte(self) -> Dict[str, Any]:
        transp = self._find("transp")
        if transp is None:
            return {}
        transporta = transp.find(".//{*}transporta")
        vol = transp.find(".//{*}vol")
        return {
            "modFrete": self._txt(transp, "modFrete"),
            "transportadora_nome": self._txt(transporta, "xNome"),
            "transportadora_cnpj": self._txt(transporta, "CNPJ") or self._txt(transporta, "CPF"),
            "uf": self._txt(transporta, "UF"),
            "qVol": self._txt(vol, "qVol"),
            "esp": self._txt(vol, "esp"),
            "marca": self._txt(vol, "marca"),
            "nVol": self._txt(vol, "nVol"),
            "pesoL": self._txt(vol, "pesoL"),
            "pesoB": self._txt(vol, "pesoB"),
        }

    # ----------------------------- Cobrança ------------------------------------
    def cobranca(self) -> Dict[str, Any]:
        cobr = self._find("cobr")
        if cobr is None:
            return {}
        fat = cobr.find(".//{*}fat")
        return {
            "nFat": self._txt(fat, "nFat"),
            "vOrig": float(q2(self._num(fat, "vOrig", Decimal("0")))),
            "vDesc": float(q2(self._num(fat, "vDesc", Decimal("0")))),
            "vLiq":  float(q2(self._num(fat, "vLiq",  Decimal("0")))),
        }

    def duplicatas(self) -> List[Dict[str, Any]]:
        cobr = self._find("cobr")
        if cobr is None:
            return []
        dups = []
        for dup in cobr.findall(".//{*}dup"):
            dups.append({
                "nDup": self._txt(dup, "nDup"),
                "dVenc": self._txt(dup, "dVenc"),
                "vDup": float(q2(self._num(dup, "vDup", Decimal("0")))),
            })
        return dups

    # ------------------------- Informações adicionais --------------------------
    def inf_adic(self) -> str:
        inf = self._find("infAdic")
        return self._txt(inf, "infCpl", "")

    # ------------------------------- Itens -------------------------------------
    def itens(self) -> List[NFItem]:
        dets = self._findall("det")
        base_items: List[Dict[str, Any]] = []
        soma_vprod = Decimal("0")

        for det in dets:
            prod    = det.find(".//{*}prod")
            imposto = det.find(".//{*}imposto")

            nItem = det.attrib.get("nItem", "").strip()
            cProd = self._txt(prod, "cProd")
            xProd = self._txt(prod, "xProd")
            ncm   = self._txt(prod, "NCM")
            cfop  = self._txt(prod, "CFOP")
            uCom  = self._txt(prod, "uCom")
            uTrib = self._txt(prod, "uTrib")
            cEAN  = self._txt(prod, "cEAN")
            cEANTrib = self._txt(prod, "cEANTrib")
            cest  = self._txt(prod, "CEST")

            qCom  = D(self._txt(prod, "qCom", "0"))
            vUnCom= D(self._txt(prod, "vUnCom", "0"))
            vProd = q2(qCom * vUnCom)

            # ICMS (CST/CSOSN e desoneração)
            cst = ""
            vICMSDeson = Decimal("0")
            icms = imposto.find(".//{*}ICMS") if imposto is not None else None
            if icms is not None:
                for child in list(icms):
                    cst = self._txt(child, "CST") or self._txt(child, "CSOSN") or ""
                    vICMSDeson = D(self._txt(child, "vICMSDeson", "0"))
                    break

            # IPI por item (se houver)
            vIPI = Decimal("0")
            ipi = imposto.find(".//{*}IPI") if imposto is not None else None
            if ipi is not None:
                vIPI = D(self._txt(ipi, "IPITrib/vIPI", "0"))

            # frete declarado no item (quando existir)
            vFrete_item = D(self._txt(prod, "vFrete", "0"))

            base_items.append({
                "nItem": nItem, "cProd": cProd, "xProd": xProd,
                "ncm": ncm, "cfop": cfop, "cst": cst,
                "qCom": qCom, "vUnCom": vUnCom, "vProd": vProd,
                "vIPI": vIPI, "vICMSDeson": vICMSDeson,
                "vFrete_item": vFrete_item,
                "uCom": uCom, "uTrib": uTrib, "cEAN": cEAN, "cEANTrib": cEANTrib, "cest": cest,
            })
            soma_vprod += vProd

        # Totais para rateio (quando o frete vem só no total)
        tot = self._find("total/ICMSTot")
        vFrete_total = self._num(tot, "vFrete", Decimal("0"))
        vOutro_total = self._num(tot, "vOutro", Decimal("0"))

        soma_frete_item = sum((bi["vFrete_item"] for bi in base_items), Decimal("0"))
        usar_frete_item = soma_frete_item > 0

        itens: List[NFItem] = []
        for bi in base_items:
            if usar_frete_item:
                vFrete_i = q2(bi["vFrete_item"])
            else:
                prop = (bi["vProd"] / soma_vprod) if soma_vprod > 0 else Decimal("0")
                vFrete_i = q2(vFrete_total * prop)

            prop = (bi["vProd"] / soma_vprod) if soma_vprod > 0 else Decimal("0")
            vOutro_i = q2(vOutro_total * prop)

            itens.append(NFItem(
                nItem=bi["nItem"],
                cProd=bi["cProd"],
                xProd=bi["xProd"],
                ncm=bi["ncm"],
                cst=bi["cst"],
                cfop=bi["cfop"],
                qCom=q2(bi["qCom"]),
                vUnCom=q2(bi["vUnCom"]),
                vProd=q2(bi["vProd"]),
                vFrete=vFrete_i,
                vIPI=q2(bi["vIPI"]),
                vOutro=vOutro_i,
                vICMSDeson=q2(bi["vICMSDeson"]),
                uCom=bi["uCom"],
                uTrib=bi["uTrib"],
                cEAN=bi["cEAN"],
                cEANTrib=bi["cEANTrib"],
                cest=bi["cest"],
            ))
        return itens
