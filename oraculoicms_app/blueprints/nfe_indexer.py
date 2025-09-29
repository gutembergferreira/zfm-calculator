# oraculoicms_app/services/nfe_indexer.py
import json
import datetime as dt

def _parse_emissao_iso(iso: str):
    if not iso:
        return None
    try:
        # aceita '2025-09-21T09:00:00-03:00' ou '...Z'
        d = dt.datetime.fromisoformat(iso.replace('Z', '+00:00'))
        # se a coluna é naive (sem tz), remova o tz:
        return d.replace(tzinfo=None) if d.tzinfo else d
    except Exception:
        return None

def upsert_summary_from_xml(db, NFEXML, NFESummary, UserFile,
                            user_id: int, xml_bytes: bytes, user_file_id: int | None = None):
    """
    Garante um NFESummary para o usuário/arquivo, preenchendo cabeçalho e totais.
    - Procura primeiro por user_file_id
    - Senão, por (user_id, chave)
    - Cria se não existir
    Retorna: (summary, created: bool)
    """
    nfe   = NFEXML(xml_bytes)
    head  = nfe.header() or {}
    totais = getattr(nfe, "totais", lambda: {})() or {}

    chave = head.get("chave")
    if not chave:
        raise ValueError("XML sem chave NF-e.")

    # 1) tenta pelo user_file_id
    summary = None
    if user_file_id:
        summary = NFESummary.query.filter_by(user_file_id=user_file_id).first()

    # 2) se não tem, tenta por (user, chave)
    if not summary:
        summary = (
            db.session.query(NFESummary)
            .join(UserFile, NFESummary.user_file_id == UserFile.id)
            .filter(UserFile.user_id == user_id, NFESummary.chave == chave)
            .first()
        )

    created = False
    if not summary:
        if not user_file_id:
            raise ValueError("Não foi possível associar o XML a um arquivo do usuário.")
        summary = NFESummary(user_file_id=user_file_id, chave=chave)
        created = True
    else:
        # garantir apontamento ao upload atual (se fornecido)
        if user_file_id and summary.user_file_id != user_file_id:
            summary.user_file_id = user_file_id

    # ——— preencher/atualizar campos usados no relatório ———
    summary.emissao   = _parse_emissao_iso(head.get("dhEmi") or head.get("emissao"))
    summary.emit_cnpj = head.get("emitente_cnpj")
    summary.dest_cnpj = head.get("destinatario_cnpj")
    summary.emit_nome = head.get("emitente_nome")
    summary.dest_nome = head.get("destinatario_nome")
    summary.numero    = head.get("numero")
    summary.serie     = head.get("serie")

    def f(x):
        try: return float(x or 0)
        except: return 0.0

    summary.valor_total    = f(totais.get("vNF"))
    summary.valor_produtos = f(totais.get("vProd"))
    summary.icms           = f(totais.get("vICMS"))
    summary.icms_st        = f(totais.get("vST") or totais.get("vICMSST"))
    summary.ipi            = f(totais.get("vIPI"))
    # PIS/COFINS nem sempre vêm agregados — mantenha 0 se ausentes
    if getattr(summary, "pis", None) is not None:
        summary.pis = f(totais.get("vPIS"))
    if getattr(summary, "cofins", None) is not None:
        summary.cofins = f(totais.get("vCOFINS"))

    # defaults obrigatórios para UX/relatórios
    if not getattr(summary, "validation_status", None):
        summary.validation_status = "pending"
    if getattr(summary, "include_in_totals", None) is None:
        summary.include_in_totals = True
    if not getattr(summary, "processed_at", None):
        # “processado” aqui significa: XML lido e indexado (não necessariamente ST calculado)
        summary.processed_at = dt.datetime.utcnow()

    # meta: header+totais para consultas rápidas
    summary.meta_json = json.dumps({"header": head, "totais": totais}, ensure_ascii=False)

    db.session.add(summary)
    db.session.commit()
    return summary, created
