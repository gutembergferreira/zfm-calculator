# zfm_app/blueprints/nfe.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import io, json, base64, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify,current_app
from oraculoicms_app.decorators import login_required, admin_required
from oraculoicms_app.services.sheets_service import get_sheet_client, get_matrices, reload_matrices
from oraculoicms_app.services.calc_service import get_motor, rebuild_motor
from updater import run_update_am
from xml_parser import NFEXML
from report import gerar_pdf
from calc import ItemNF, ResultadoItem
from base64 import b64decode
from oraculoicms_app.extensions import db
from oraculoicms_app.models.file import NFESummary, UserFile
from .files import current_user  # usa o helper que criamos
from datetime import datetime

bp = Blueprint("nfe", __name__)
ALLOWED_EXT = {"xml"}

# --- helper: um único lugar com a regra de cálculo ---
ALG_VERSION = "st-v1"  # mude se alterar a lógica e quiser invalidar caches

def _compute_st_payload(xml_bytes, NFEXML, get_motor):
    nfe = NFEXML(xml_bytes)
    header = nfe.header() or {}
    itens  = nfe.itens() or []

    uf_origem  = (header.get("uf_origem")  or "SP").upper()
    uf_destino = (header.get("uf_destino") or "AM").upper()

    motor = get_motor()
    linhas, total_st = [], 0.0
    for it in itens:
        r = motor.calcula_st(it, uf_origem, uf_destino, usar_multiplicador=True)
        m = r.memoria

        def f(v, d=0.0):
            try: return float(v if v is not None else d)
            except: return float(d)

        qCom=f(it.qCom); vUnCom=f(it.vUnCom); vProd=f(it.vProd)
        vFrete=f(it.vFrete); vIPI=f(it.vIPI); vOutro=f(it.vOutro)
        vICMSDeson_xml=f(it.vICMSDeson)
        vICMSDeson=f(m.get("ICMS DESONERADO", vICMSDeson_xml))

        venda_desc_icms=f(m.get("VALOR DA VENDA COM DESCONTO DE ICMS", m.get("venda_desc_icms", 0.0)))
        valor_oper=f(m.get("VALOR DA OPERAÇÃO", venda_desc_icms))
        mva_percent=f(m.get("MARGEM_DE_VALOR_AGREGADO_MVA", m.get("mva_percentual_aplicado", 0.0)))
        valor_agregado=f(m.get("VALOR AGREGADO", 0.0))
        base_st=f(m.get("BASE_ST", m.get("BASE DE CÁLCULO SUBSTITUIÇÃO TRIBUTÁRIA", 0.0)))
        aliq_st=f(m.get("ALÍQUOTA ICMS-ST", m.get("aliq_interna", 0.0)))
        icms_teorico_dest=f(m.get("icms_teorico_dest", 0.0))
        icms_origem_calc=f(m.get("icms_origem_calc", vICMSDeson))
        icms_st=f(m.get("VALOR_ICMS_ST", 0.0))
        saldo_devedor=f(m.get("SALDO_DEVEDOR_ST", m.get("VALOR SALDO DEVEDOR ICMS ST", 0.0)))
        mult_sefaz=f(m.get("MULT_SEFAZ", m.get("Multiplicador", m.get("MULTIPLICADOR SEFAZ", 0.0))))
        icms_retido=f(m.get("VALOR ICMS RETIDO", m.get("icms_retido", saldo_devedor)))

        linhas.append({
            "idx": it.nItem, "cProd": it.cProd, "xProd": it.xProd,
            "ncm": it.ncm, "cst": it.cst, "cfop": it.cfop,
            "qCom": qCom, "vUnCom": vUnCom, "vProd": vProd,
            "vFrete": vFrete, "vIPI": vIPI, "vOutro": vOutro,
            "vICMSDeson": vICMSDeson,
            "venda_desc_icms": venda_desc_icms,
            "valor_oper": valor_oper,
            "mva_tipo": m.get("mva_tipo", "MVA Padrão"),
            "mva_percent": mva_percent,
            "valor_agregado": valor_agregado,
            "base_st": base_st,
            "aliq_st": aliq_st,
            "icms_teorico_dest": icms_teorico_dest,
            "icms_origem_calc": icms_origem_calc,
            "icms_st": icms_st,
            "saldo_devedor": saldo_devedor,
            "mult_sefaz": mult_sefaz,
            "icms_retido": icms_retido,

            # aliases que seus templates usam
            "valor_operacao": valor_oper,
            "mva_percentual": mva_percent,
            "multiplicador": mult_sefaz,
            "quant": qCom, "vun": vUnCom, "vprod": vProd, "frete": vFrete, "ipi": vIPI, "vout": vOutro,
            "icms_deson": vICMSDeson,
            "base_calculo_st": base_st,
            "aliquota_icms_st": aliq_st,
            "valor_icms_st": icms_st,
            "valor_saldo_devedor": saldo_devedor,
            "multiplicador_sefaz": mult_sefaz,
            "valor_icms_retido": icms_retido,
        })
        total_st += float(r.icms_st_devido or 0.0)

    return {
        "uf_origem": uf_origem,
        "uf_destino": uf_destino,
        "linhas": linhas,
        "total_st": total_st,
    }


def allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def _xml_from_request() -> bytes | None:
    # mantém a sua implementação atual; mostro uma robusta só pra referência:
    f = request.files.get("xml")
    if f and getattr(f, "filename", ""):
        data = f.read()
        if data:
            return data
    txt = (request.form.get("xml_text") or "").strip()
    if txt:
        if "base64," in txt:
            try:
                return b64decode(txt.split("base64,", 1)[1])
            except Exception:
                pass
        return txt.encode("utf-8", "ignore")
    b64 = (request.form.get("xml_b64") or "").strip()
    if b64:
        try:
            return b64decode(b64)
        except Exception:
            return None
    return None

# --------- NF-e: Preview / Calcular / Exportar PDF ---------

@bp.route("/preview", methods=["POST"])
@login_required
def preview():
    xml_bytes = _xml_from_request()
    if not xml_bytes:
        flash("Envie um arquivo XML válido.")
        return redirect(url_for("core.index"))

    nfe = NFEXML(xml_bytes)
    head   = nfe.header()
    itens  = nfe.itens()
    totais = nfe.totais()
    transp = nfe.transporte()
    cobr   = nfe.cobranca()
    dups   = nfe.duplicatas()
    obs    = nfe.inf_adic()

    xml_b64 = base64.b64encode(xml_bytes).decode("ascii")
    return render_template(
        "preview.html",
        head=head, itens=itens, itens_count=len(itens),
        totais=totais, transp=transp, cobr=cobr,
        duplicatas=dups, inf_cpl=obs, xml_b64=xml_b64
    )

@bp.route("/calcular", methods=["POST"])
@login_required
def calcular():
    xml_bytes = _xml_from_request()
    if not xml_bytes:
        flash("Não foi possível recuperar o XML.", "danger")
        return redirect(url_for("core.index"))

    import hashlib, datetime, json as _json
    md5 = hashlib.md5(xml_bytes).hexdigest()

    # localizar upload do usuário por md5 (se existir)
    uf = (UserFile.query
          .filter_by(user_id=current_user().id, md5=md5, deleted_at=None)
          .order_by(UserFile.id.desc())
          .first())

    # tenta garantir summary (indexar p/ relatório), reaproveitando se já existir
    summary = None
    try:
        if uf:
            # upsert devolve o summary do próprio arquivo do usuário
            summary, _ = upsert_summary_from_xml(
                db, NFEXML, NFESummary, UserFile, current_user().id, xml_bytes, uf.id
            )
        else:
            # sem upload correspondente: tenta achar por chave para o usuário
            nfe = NFEXML(xml_bytes); header = nfe.header() or {}
            chave = header.get("chave")
            if chave:
                summary = (db.session.query(NFESummary)
                           .join(UserFile, NFESummary.user_file_id==UserFile.id)
                           .filter(UserFile.user_id==current_user().id, NFESummary.chave==chave)
                           .first())
    except Exception as e:
        current_app.logger.warning("indexer falhou: %s", e)
        # segue sem summary (somente renderização)

    # Se houver cache válido, usa e retorna já
    if summary and summary.calc_json and summary.calc_version == ALG_VERSION:
        payload = _json.loads(summary.calc_json)
        return render_template(
            "resultado.html",
            linhas=payload.get("linhas", []),
            total_st=float(payload.get("total_st", 0)),
            uf_origem=payload.get("uf_origem", "SP"),
            uf_destino=payload.get("uf_destino", "AM"),
            payload_json=_json.dumps(payload, ensure_ascii=False)
        )

    # Calcula usando o helper (uma única fonte de verdade)
    payload = _compute_st_payload(xml_bytes, NFEXML, get_motor)

    # Salva cache (se houver summary)
    if summary:
        summary.calc_json    = _json.dumps(payload, ensure_ascii=False)
        summary.calc_version = ALG_VERSION
        summary.calc_at      = datetime.datetime.utcnow()
        if not summary.processed_at:
            summary.processed_at = datetime.datetime.utcnow()
        db.session.add(summary); db.session.commit()

    return render_template(
        "resultado.html",
        linhas=payload["linhas"],
        total_st=payload["total_st"],
        uf_origem=payload["uf_origem"],
        uf_destino=payload["uf_destino"],
        payload_json=_json.dumps(payload, ensure_ascii=False)
    )



@bp.route("/exportar-pdf", methods=["POST"])
@login_required
def exportar_pdf():
    data_json = request.form.get("data")
    if not data_json:
        flash("Dados ausentes para gerar o PDF.", "danger")
        return redirect(url_for("core.index"))

    data = data_json
    try:
        cnt = 0
        while isinstance(data, str) and cnt < 3:
            data = json.loads(data)
            cnt += 1
    except Exception as e:
        flash(f"Payload inválido para PDF: {e}", "danger")
        return redirect(url_for("core.index"))

    resultados = []
    for row in data["linhas"]:
        it_fake = ItemNF(
            ncm=row.get("ncm",""), cfop=row.get("cfop",""), cst=row.get("cst",""),
            valor_produto=0.0, frete_rateado=0.0, descontos=0.0,
            despesas_acessorias=0.0, icms_destacado_origem=0.0
        )
        r_fake = ResultadoItem(
            base_calculo_st=row.get("base_st", 0.0),
            icms_st_devido=row.get("icms_st", 0.0),
            memoria={
                "base_oper": row.get("base_oper", 0.0),
                "mva_tipo": row.get("mva_tipo", "-"),
                "mva_percentual_aplicado": row.get("mva_percentual", 0.0),
                "icms_teorico_dest": row.get("icms_teorico_dest", 0.0),
                "icms_origem_calc": row.get("icms_origem_calc", 0.0),
            }
        )
        resultados.append((it_fake, r_fake))

    pdf_bytes = gerar_pdf(resultados, data.get("uf_origem","-"), data.get("uf_destino","-"))
    return send_file(io.BytesIO(pdf_bytes),
                     mimetype="application/pdf", as_attachment=True,
                     download_name="memoria_calculo_icms.pdf")

# --------- Admin: updater/config (planilhas) ---------

@bp.route("/admin/run-update")
@admin_required
def run_update():
    sc = get_sheet_client()
    run_update_am(sc)
    reload_matrices()
    rebuild_motor()
    flash("Atualização AM executada e parâmetros recarregados.", "success")
    return redirect(url_for("core.index"))

@bp.route("/admin/reload")
@admin_required
def admin_reload():
    reload_matrices()
    rebuild_motor()
    flash("Parâmetros recarregados do Google Sheets.", "info")
    return redirect(url_for("core.index"))

@bp.route("/config", methods=["GET"])
@admin_required
def config_view():
    matrices = get_matrices()
    df_sources = matrices.get("sources")
    if df_sources is None:
        import pandas as pd
        df_sources = pd.DataFrame(columns=["ATIVO","UF","NOME","URL","TIPO","PARSER","PRIORIDADE"])

    try:
        sh = get_sheet_client().sh
        worksheets = [{"title": ws.title, "rows": ws.row_count, "cols": ws.col_count} for ws in sh.worksheets()]
        sheet_title = sh.title
        service_email = get_sheet_client().service_email
    except Exception:
        worksheets, sheet_title, service_email = [], None, None

    sources = df_sources.fillna("").to_dict(orient="records")
    columns = list(df_sources.columns)
    updated_at = datetime.now().isoformat(timespec="seconds")
    sources_count = sum(1 for r in sources if str(r.get("ATIVO","")).strip() in ("1","true","True","on","ON"))

    return render_template("config.html",
        sources=sources, columns=columns,
        sheet_title=sheet_title, service_email=service_email,
        worksheets=worksheets, updated_at=updated_at, sources_count=sources_count
    )

@bp.route("/config/save", methods=["POST"])
@admin_required
def config_save():
    cols = request.form.getlist("cols[]")
    try:
        row_count = int(request.form.get("row_count", "0"))
    except ValueError:
        row_count = 0

    rows = []
    for i in range(row_count):
        row = []
        for c in cols:
            val = request.form.get(f"row-{i}-{c}", "").strip()
            row.append(val)
        if any(row):
            rows.append(row)

    import pandas as pd
    df_new = pd.DataFrame(rows, columns=cols)

    if "ATIVO" in df_new.columns:
        df_new["ATIVO"] = df_new["ATIVO"].apply(lambda x: "1" if str(x).strip() in ("1","true","True","on","ON") else "0")
    if "PRIORIDADE" in df_new.columns:
        df_new["PRIORIDADE"] = df_new["PRIORIDADE"].apply(lambda x: str(x).strip() if str(x).strip().isdigit() else "")

    try:
        get_sheet_client().write_df("sources", df_new)
        reload_matrices()
        rebuild_motor()
        flash("Fontes salvas com sucesso.", "success")
    except Exception as e:
        flash(f"Falha ao salvar fontes: {e}", "danger")

    return redirect(url_for("nfe.config_view"))

# Diagnóstico opcional
@bp.route("/debug/sheets")
def debug_sheets():
    try:
        sc = get_sheet_client()
        info = {
            "service_email": sc.service_email,
            "spreadsheet_title": sc.sh.title,
            "worksheets": [ws.title for ws in sc.sh.worksheets()],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        return jsonify(info), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
