from xml.etree import ElementTree as ET
from typing import List, Dict, Any
from calc import ItemNF

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

def _txt(node, path: str) -> str:
    el = node.find(path, NS)
    return el.text.strip() if el is not None and el.text else ""

def _num(s: str) -> float:
    try:
        return float(str(s).replace(",", ".")) if s not in (None, "") else 0.0
    except Exception:
        return 0.0

class NFEXML:
    def __init__(self, content: bytes):
        self.doc = ET.fromstring(content)

    def header(self) -> Dict[str, Any]:
        ide = self.doc.find(".//nfe:ide", NS)
        emit = self.doc.find(".//nfe:emit", NS)
        dest = self.doc.find(".//nfe:dest", NS)
        chave = ""
        inf = self.doc.find(".//nfe:infNFe", NS)
        if inf is not None:
            chave = (inf.attrib.get("Id", "") or "").replace("NFe", "")
        if not chave:
            chave = _txt(self.doc, ".//nfe:protNFe/nfe:infProt/nfe:chNFe")
        return {
            "chave": chave,
            "emitente_nome": _txt(emit, "nfe:xNome"),
            "emitente_cnpj": _txt(emit, "nfe:CNPJ"),
            "dest_nome": _txt(dest, "nfe:xNome"),
            "dest_cnpj": _txt(dest, "nfe:CNPJ"),
            "numero": _txt(ide, "nfe:nNF"),
            "serie": _txt(ide, "nfe:serie"),
            "dhEmi": _txt(ide, "nfe:dhEmi") or _txt(ide, "nfe:dEmi"),
            "natOp": _txt(ide, "nfe:natOp"),
            "uf_origem": _txt(emit, "nfe:enderEmit/nfe:UF"),
            "uf_destino": _txt(dest, "nfe:enderDest/nfe:UF"),
        }

    def itens_detalhados(self) -> List[Dict[str, Any]]:
        linhas = []
        for det in self.doc.findall(".//nfe:det", NS):
            prod = det.find(".//nfe:prod", NS)
            if prod is None:
                continue
            cst = ""
            icms_parent = det.find(".//nfe:ICMS", NS)
            if icms_parent is not None:
                for child in icms_parent:
                    cst_el = child.find("nfe:CST", NS)
                    if cst_el is not None and cst_el.text:
                        cst = cst_el.text
                        break
            linhas.append({
                "seq": det.attrib.get("nItem", ""),
                "codigo": _txt(prod, "nfe:cProd"),
                "descricao": _txt(prod, "nfe:xProd"),
                "ncm": _txt(prod, "nfe:NCM"),
                "cst": cst,
                "cfop": _txt(prod, "nfe:CFOP"),
                "uCom": _txt(prod, "nfe:uCom"),
                "qCom": _num(_txt(prod, "nfe:qCom")),
                "vUnCom": _num(_txt(prod, "nfe:vUnCom")),
                "vProd": _num(_txt(prod, "nfe:vProd")),
            })
        return linhas

    def itens(self) -> List[ItemNF]:
        dets = self.doc.findall(".//nfe:det", NS)

        # total de frete da NF (vFrete pode estar em ICMSTot ou em transp)
        vfrete_total = _num(_txt(self.doc, ".//nfe:total/nfe:ICMSTot/nfe:vFrete")) \
            or _num(_txt(self.doc, ".//nfe:transp/nfe:vFrete"))

        # somatório para rateio do frete
        soma_vprod = 0.0
        vprod_list = []
        for det in dets:
            prod = det.find(".//nfe:prod", NS)
            vp = _num(_txt(prod, "nfe:vProd")) if prod is not None else 0.0
            vprod_list.append(vp)
            soma_vprod += vp
        soma_vprod = soma_vprod if soma_vprod > 0 else 1.0

        itens: List[ItemNF] = []
        for idx, det in enumerate(dets, start=1):
            prod = det.find(".//nfe:prod", NS)
            if prod is None:
                continue

            # ICMS grupo
            icms_parent = det.find(".//nfe:ICMS", NS)
            cst = ""
            vicms_origem = 0.0
            vicms_deson = 0.0
            mot_des = ""
            vicms_st_retido = 0.0  # vICMSST no item (se o emissor reteve)

            if icms_parent is not None:
                for child in icms_parent:
                    cst_el = child.find("nfe:CST", NS)
                    if cst_el is not None and cst_el.text:
                        cst = cst_el.text
                    vICMS = child.find("nfe:vICMS", NS)
                    if vICMS is not None and vICMS.text:
                        vicms_origem = _num(vICMS.text)
                    vDes = child.find("nfe:vICMSDeson", NS)
                    if vDes is not None and vDes.text:
                        vicms_deson = _num(vDes.text)
                    mot = child.find("nfe:motDesICMS", NS)
                    if mot is not None and mot.text:
                        mot_des = mot.text
                    vICMSST = child.find("nfe:vICMSST", NS)
                    if vICMSST is not None and vICMSST.text:
                        vicms_st_retido = _num(vICMSST.text)

            # IPI do item
            ipi = 0.0
            ipi_node = det.find(".//nfe:IPI", NS)
            if ipi_node is not None:
                vipi = ipi_node.find(".//nfe:vIPI", NS)
                if vipi is not None and vipi.text:
                    ipi = _num(vipi.text)

            # campos de produto
            ncm = _txt(prod, "nfe:NCM")
            cfop = _txt(prod, "nfe:CFOP")
            cest = _txt(prod, "nfe:CEST")
            vprod = _num(_txt(prod, "nfe:vProd"))
            vun = _num(_txt(prod, "nfe:vUnCom"))
            qcom = _num(_txt(prod, "nfe:qCom"))
            vdesc = _num(_txt(prod, "nfe:vDesc"))
            vout  = _num(_txt(prod, "nfe:vOutro"))
            vfrete_item = _num(_txt(prod, "nfe:vFrete"))

            # rateio do frete total, se não houver por item
            if vfrete_item == 0.0 and vfrete_total > 0:
                proporcao = (vprod / soma_vprod) if soma_vprod else 0.0
                vfrete_item = vfrete_total * proporcao

            itens.append(ItemNF(
                seq=str(det.attrib.get("nItem", idx)),
                codigo=_txt(prod, "nfe:cProd"),
                descricao=_txt(prod, "nfe:xProd"),
                ncm=ncm,
                cfop=cfop,
                cst=cst,
                quantidade=qcom,
                valor_unitario=vun,
                valor_produto=vprod,
                frete_rateado=vfrete_item,
                descontos=vdesc,
                despesas_acessorias=vout,
                ipi=ipi,
                icms_destacado_origem=vicms_origem,
                icms_desonerado=vicms_deson,
                motivo_desoneracao=mot_des,
                icms_st_retido=vicms_st_retido,
                cest=cest
            ))

        return itens
