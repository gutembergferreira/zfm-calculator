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
    if isinstance(x, Decimal): return x
    if x is None: return Decimal("0")
    s = str(x).strip()
    if "." in s and "," in s and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try: return Decimal(s or "0")
    except Exception: return Decimal("0")

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
    uCom: str = ""
    uTrib: str = ""
    cEAN: str = ""
    cEANTrib: str = ""
    cest: str = ""

class NFEXML:
    def __init__(self, xml_bytes: bytes):
        # aceita NFe e nfeProc
        self.root = ET.fromstring(xml_bytes)

    # ---------- helpers com wildcard por segmento ----------
    def _mkpath(self, path: str) -> str:
        parts = [p for p in path.split("/") if p]
        return ".//" + "/".join(f"{{*}}{p}" for p in parts)

    def _find(self, path: str) -> Optional[ET.Element]:
        return self.root.find(self._mkpath(path))

    def _findall(self, path: str) -> List[ET.Element]:
        return self.root.findall(self._mkpath(path))

    def _txt(self, el: Optional[ET.Element], path: str, default: str = "") -> str:
        try:
            if el is None:
                val = self.root.findtext(self._mkpath(path))
            else:
                # relativo ao elemento: também aplicar wildcard por segmento
                val = el.findtext(self._mkpath(path))
            return (val or default).strip()
        except Exception:
            return default

    def _num(self, el: Optional[ET.Element], path: str) -> Decimal:
        if el is None:
            return D(self._txt(None, path, "0"))
        val = el.findtext(self._mkpath(path))
        return D(val or "0")

    # ---------------------- Cabeçalho (achatado) ----------------------
    def header(self) -> Dict[str, Any]:
        ide   = self._find("ide")
        emit  = self._find("emit")
        dest  = self._find("dest")
        infNFe= self._find("infNFe")

        # endereço amigável
        def addr(block: str, parent: Optional[ET.Element]) -> Dict[str, str]:
            e = parent.find(self._mkpath(block)) if parent is not None else None
            xLgr = self._txt(e, "xLgr")
            nro  = self._txt(e, "nro")
            xBai = self._txt(e, "xBairro")
            xMun = self._txt(e, "xMun")
            uf   = self._txt(e, "UF")
            cep  = self._txt(e, "CEP")
            end = ", ".join([p for p in [xLgr, nro, xBai] if p])
            return {"end": end, "mun": xMun, "uf": uf, "cep": cep}

        emit_addr = addr("enderEmit", emit)
        dest_addr = addr("enderDest", dest)

        chave = (infNFe.attrib.get("Id", "") if infNFe is not None else "").replace("NFe", "")

        return {
            "chave":  chave,
            "numero": self._txt(ide, "nNF"),
            "serie":  self._txt(ide, "serie"),
            "modelo": self._txt(ide, "mod"),
            "natOp":  self._txt(ide, "natOp"),
            "dhEmi":  self._txt(ide, "dhEmi") or self._txt(ide, "dEmi"),
            "dhSaiEnt": self._txt(ide, "dhSaiEnt") or self._txt(ide, "dSaiEnt"),

            "emitente_nome": self._txt(emit, "xNome"),
            "emitente_cnpj": self._txt(emit, "CNPJ") or self._txt(emit, "CPF"),
            "emitente_ie":   self._txt(emit, "IE"),
            "emitente_endereco":   emit_addr["end"],
            "emitente_municipio":  emit_addr["mun"],
            "emitente_uf":         emit_addr["uf"],
            "emitente_cep":        emit_addr["cep"],

            "dest_nome": self._txt(dest, "xNome"),
            "dest_cnpj": self._txt(dest, "CNPJ") or self._txt(dest, "CPF"),
            "dest_ie":   self._txt(dest, "IE"),
            "dest_isuf": self._txt(dest, "ISUF"),
            "dest_endereco":   dest_addr["end"],
            "dest_municipio":  dest_addr["mun"],
            "dest_uf":         dest_addr["uf"],
            "dest_cep":        dest_addr["cep"],

            "uf_origem":  emit_addr["uf"],
            "uf_destino": dest_addr["uf"],
        }

    # ------------------------------ Totais -------------------------------------
    def totais(self) -> Dict[str, float]:
        icmstot = self._find("total/ICMSTot")
        if icmstot is None:
            return {}
        def f(k): return float(q2(self._num(icmstot, k)))
        keys = ["vProd","vFrete","vIPI","vDesc","vOutro","vICMSDeson","vNF"]
        return {k: f(k) for k in keys}

    # ------------------------------- Itens -------------------------------------
    def itens(self) -> List[NFItem]:
        dets = self._findall("det")
        tmp: List[Dict[str, Any]] = []
        soma_vprod = Decimal("0")

        for det in dets:
            prod = det.find(self._mkpath("prod"))
            imposto = det.find(self._mkpath("imposto"))

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

            # ICMS
            cst = ""
            vICMSDeson = Decimal("0")
            icms = imposto.find(self._mkpath("ICMS")) if imposto is not None else None
            if icms is not None:
                for child in list(icms):
                    cst = self._txt(child, "CST") or self._txt(child, "CSOSN") or ""
                    vICMSDeson = D(self._txt(child, "vICMSDeson", "0"))
                    break

            vIPI = Decimal("0")
            ipi = imposto.find(self._mkpath("IPI")) if imposto is not None else None
            if ipi is not None:
                vIPI = D(self._txt(ipi, "IPITrib/vIPI", "0"))

            vFrete_item = D(self._txt(prod, "vFrete", "0"))

            tmp.append({
                "nItem": nItem, "cProd": cProd, "xProd": xProd,
                "ncm": ncm, "cfop": cfop, "cst": cst,
                "qCom": qCom, "vUnCom": vUnCom, "vProd": vProd,
                "vIPI": vIPI, "vICMSDeson": vICMSDeson,
                "vFrete_item": vFrete_item,
                "uCom": uCom, "uTrib": uTrib, "cEAN": cEAN, "cEANTrib": cEANTrib, "cest": cest,
            })
            soma_vprod += vProd

        # rateio frete/outros
        icmstot = self._find("total/ICMSTot")
        vFrete_total = self._num(icmstot, "vFrete") if icmstot is not None else Decimal("0")
        vOutro_total = self._num(icmstot, "vOutro") if icmstot is not None else Decimal("0")

        soma_frete_item = sum((r["vFrete_item"] for r in tmp), Decimal("0"))
        usar_frete_item = soma_frete_item > 0

        itens: List[NFItem] = []
        for r in tmp:
            if usar_frete_item:
                vFrete_i = q2(r["vFrete_item"])
            else:
                prop = (r["vProd"]/soma_vprod) if soma_vprod > 0 else Decimal("0")
                vFrete_i = q2(vFrete_total * prop)

            prop = (r["vProd"]/soma_vprod) if soma_vprod > 0 else Decimal("0")
            vOutro_i = q2(vOutro_total * prop)

            itens.append(NFItem(
                nItem=r["nItem"], cProd=r["cProd"], xProd=r["xProd"],
                ncm=r["ncm"], cst=r["cst"], cfop=r["cfop"],
                qCom=q2(r["qCom"]), vUnCom=q2(r["vUnCom"]), vProd=q2(r["vProd"]),
                vFrete=vFrete_i, vIPI=q2(r["vIPI"]), vOutro=vOutro_i, vICMSDeson=q2(r["vICMSDeson"]),
                uCom=r["uCom"], uTrib=r["uTrib"], cEAN=r["cEAN"], cEANTrib=r["cEANTrib"], cest=r["cest"],
            ))
        return itens

    # extras usados no template (se quiser usar depois)
    def transporte(self) -> Dict[str, Any]:
        transp = self._find("transp")
        if transp is None: return {}
        transporta = transp.find(self._mkpath("transporta"))
        vol = transp.find(self._mkpath("vol"))
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

    def cobranca(self) -> Dict[str, Any]:
        cobr = self._find("cobr")
        if cobr is None: return {}
        fat = cobr.find(self._mkpath("fat"))
        def _f(k): return float(q2(self._num(fat, k))) if fat is not None else 0.0
        return {"nFat": self._txt(fat, "nFat"), "vOrig": _f("vOrig"), "vDesc": _f("vDesc"), "vLiq": _f("vLiq")}

    def duplicatas(self) -> List[Dict[str, Any]]:
        cobr = self._find("cobr")
        if cobr is None: return []
        out = []
        for dup in cobr.findall(self._mkpath("dup")):
            out.append({"nDup": self._txt(dup,"nDup"), "dVenc": self._txt(dup,"dVenc"), "vDup": float(q2(self._num(dup,"vDup")))})
        return out

    def inf_adic(self) -> str:
        inf = self._find("infAdic")
        return self._txt(inf, "infCpl", "")
