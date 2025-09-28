# oraculoicms_app/services/nfe_indexer.py
import datetime as dt

def upsert_summary_from_xml(db, NFEXML, NFESummary, UserFile, user_id:int, xml_bytes:bytes, user_file_id:int|None=None):
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
    if not summary and chave:
        summary = (db.session.query(NFESummary)
                   .join(UserFile, NFESummary.user_file_id==UserFile.id)
                   .filter(UserFile.user_id==user_id, NFESummary.chave==chave)
                   .first())

    created = False
    if not summary:
        # 3) cria
        if not user_file_id:
            raise ValueError("Não foi possível associar o XML a um arquivo do usuário.")
        summary = NFESummary(user_file_id=user_file_id)
        summary.chave = chave
        created = True
    else:
        # opcional: garantir que aponta para o upload atual
        if user_file_id and summary.user_file_id != user_file_id:
            summary.user_file_id = user_file_id

    # ——— preencher/atualizar campos usados no relatório ———
    # data emissão
    emissao = head.get("dhEmi") or head.get("emissao")
    emissao_dt = None
    if isinstance(emissao, str):
        try:
            emissao_dt = dt.datetime.fromisoformat(emissao.replace("Z", "+00:00"))
            # se sua coluna é naive (sem tz), remova o tz:
            if emissao_dt.tzinfo:
                emissao_dt = emissao_dt.replace(tzinfo=None)
        except Exception:
            emissao_dt = None
    elif isinstance(emissao, dt.datetime):
        emissao_dt = emissao

    summary.emissao   = emissao_dt
    summary.emit_cnpj = head.get("emitente_cnpj")
    summary.dest_cnpj = head.get("destinatario_cnpj")
    summary.emit_nome = head.get("emitente_nome")
    summary.dest_nome = head.get("destinatario_nome")
    summary.numero    = head.get("numero")
    summary.serie     = head.get("serie")

    def f(x):
        try: return float(x or 0)
        except: return 0.0

    summary.valor_total = f(totais.get("vNF"))
    summary.valor_produtos = f(totais.get("vProd"))
    summary.icms        = f(totais.get("vICMS"))
    summary.icms_st     = f(totais.get("vST") or totais.get("vICMSST"))

    # defaults
    if not summary.validation_status:
        summary.validation_status = "pending"
    if summary.include_in_totals is None:
        summary.include_in_totals = True
    if not summary.processed_at:
        summary.processed_at = dt.datetime.utcnow()

    db.session.add(summary)
    db.session.commit()
    return summary, created
