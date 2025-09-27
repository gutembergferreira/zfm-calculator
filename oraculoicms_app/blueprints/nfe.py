# zfm_app/blueprints/nfe.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import io, json, base64
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from oraculoicms_app.decorators import login_required, admin_required
from oraculoicms_app.services.sheets_service import get_sheet_client, get_matrices, reload_matrices
from oraculoicms_app.services.calc_service import get_motor, rebuild_motor
from updater import run_update_am
from xml_parser import NFEXML
from report import gerar_pdf
from calc import ItemNF, ResultadoItem

bp = Blueprint("nfe", __name__)

ALLOWED_EXT = {"xml"}

def allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def _xml_from_request():
    if "file" in request.files:
        f = request.files["file"]
        if f and f.filename:
            return f.read()
    xml_b64 = request.form.get("xml_b64")
    if xml_b64:
        try:
            return base64.b64decode(xml_b64)
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
        flash("Não foi possível recuperar o XML.")
        return redirect(url_for("core.index"))

    nfe = NFEXML(xml_bytes)
    itens = nfe.itens()
    header = nfe.header()
    uf_origem  = (header.get("uf_origem") or "SP").upper()
    uf_destino = (header.get("uf_destino") or "AM").upper()

    motor = get_motor()

    linhas, total_st = [], 0.0
    for it in itens:
        r = motor.calcula_st(it, uf_origem, uf_destino, usar_multiplicador=True)
        m = r.memoria

        qCom   = float(it.qCom); vUnCom = float(it.vUnCom); vProd  = float(it.vProd)
        vFrete = float(it.vFrete); vIPI = float(it.vIPI); vOutro = float(it.vOutro)
        vICMSDeson_xml = float(it.vICMSDeson)
        vICMSDeson = float(m.get("ICMS DESONERADO", vICMSDeson_xml))

        venda_desc_icms = float(m.get("VALOR DA VENDA COM DESCONTO DE ICMS", m.get("venda_desc_icms", 0.0)))
        valor_oper = float(m.get("VALOR DA OPERAÇÃO", venda_desc_icms))
        mva_percent = float(m.get("MARGEM_DE_VALOR_AGREGADO_MVA", m.get("mva_percentual_aplicado", 0.0)))
        valor_agregado = float(m.get("VALOR AGREGADO", 0.0))
        base_st = float(m.get("BASE_ST", m.get("BASE DE CÁLCULO SUBSTITUIÇÃO TRIBUTÁRIA", 0.0)))
        aliq_st = float(m.get("ALÍQUOTA ICMS-ST", m.get("aliq_interna", 0.0)))
        icms_teorico_dest = float(m.get("icms_teorico_dest", 0.0))
        icms_origem_calc  = float(m.get("icms_origem_calc", vICMSDeson))
        icms_st = float(m.get("VALOR_ICMS_ST", 0.0))
        saldo_devedor = float(m.get("SALDO_DEVEDOR_ST", m.get("VALOR SALDO DEVEDOR ICMS ST", 0.0)))
        mult_sefaz = float(m.get("MULT_SEFAZ", m.get("Multiplicador", m.get("MULTIPLICADOR SEFAZ", 0.0))))
        icms_retido = float(m.get("VALOR ICMS RETIDO", m.get("icms_retido", saldo_devedor)))

        linha = {
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
            # aliases usados no template antigo:
            "valor_operacao": valor_oper,
            "mva_percentual": mva_percent,
            "multiplicador": mult_sefaz,
        }
        # —— ALIASES esperados pelo seu resultado.html ——
        linha.update({
            "quant": qCom, "vun": vUnCom, "vprod": vProd, "frete": vFrete, "ipi": vIPI, "vout": vOutro,
            "icms_deson": vICMSDeson,

            "valor_operacao": valor_oper,
            "mva_percentual": mva_percent,
            "base_calculo_st": base_st,
            "aliquota_icms_st": aliq_st,
            "valor_icms_st": icms_st,
            "valor_saldo_devedor": saldo_devedor,
            "multiplicador_sefaz": mult_sefaz,
            "multiplicador": mult_sefaz,  # <— NOVO (fração; o template multiplica por 100)
            "valor_icms_retido": icms_retido,
        })
        # ————————————————————————————————
        linhas.append(linha)
        total_st += float(r.icms_st_devido or 0.0)

    payload = {"uf_origem": uf_origem, "uf_destino": uf_destino, "linhas": linhas, "total_st": total_st}
    payload_json = json.dumps(payload)

    return render_template("resultado.html",
                           linhas=linhas, total_st=total_st,
                           uf_origem=uf_origem, uf_destino=uf_destino,
                           payload_json=payload_json)

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
