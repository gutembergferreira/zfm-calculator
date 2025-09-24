# app.py
# -*- coding: utf-8 -*-
import io
import json
from datetime import datetime
import base64
import pandas as pd
from flask import (
    Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
)
from apscheduler.schedulers.background import BackgroundScheduler

# suas importações locais
from config import Config                  # <- garante que é a classe Config
from calc import MotorCalculo, ItemNF, ResultadoItem
from sheets import SheetClient
from xml_parser import NFEXML
from report import gerar_pdf
from updater import run_update_am

app = Flask(__name__)
app.config.from_object(Config)

# ---------------------------------------
# Inicialização: Sheets + motor de cálculo
# ---------------------------------------
sheet_client = SheetClient()
matrices = sheet_client.matrices()
motor = MotorCalculo(matrices)
ALLOWED_EXT = {"xml"}

def allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def _reload_params():
    global matrices, motor
    matrices = sheet_client.matrices()
    motor = MotorCalculo(matrices)   # <<< passar matrices

# ---------------------------------------
# Agendador mensal (dia 1 às 03:00)
# ---------------------------------------
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(lambda: run_update_am(sheet_client), "cron", day=1, hour=3, minute=0)
scheduler.start()

def _xml_from_request():
    # 1) upload de arquivo
    if "file" in request.files:
        f = request.files["file"]
        if f and f.filename:
            return f.read()
    # 2) xml vindo da tela de pré-visualização (hidden)
    xml_b64 = request.form.get("xml_b64")
    if xml_b64:
        try:
            return base64.b64decode(xml_b64)
        except Exception:
            return None
    return None
# ---------------------------------------
# Rotas
# ---------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/preview", methods=["POST"])
def preview():
    xml_bytes = _xml_from_request()
    if not xml_bytes:
        flash("Envie um arquivo XML válido.")
        return redirect(url_for("index"))

    nfe = NFEXML(xml_bytes)

    # Cabeçalho e itens (mantém compatível com seu template atual)
    head = nfe.header()            # pode ser dict ou objeto simples
    itens = nfe.itens()            # lista de objetos com cProd, xProd, NCM etc.

    # Blocos extras (totais, transporte, cobrança, duplicatas, observações)
    # Os getters abaixo são usados só se existirem no seu NFEXML;
    # caso não existam, caem num default seguro.
    def _get(callable_name, default):
        try:
            func = getattr(nfe, callable_name, None)
            return func() if callable(func) else default
        except Exception:
            return default

    totais      = _get("totais", {})
    transp      = _get("transporte", {})
    cobr        = _get("cobranca", {})
    duplicatas  = _get("duplicatas", [])
    inf_cpl     = _get("inf_adic", "")

    # UFs para já preencher a barrinha do "Calcular ST"
    # (usa o que vier do header; se não vier, usa defaults)
    uf_origem  = getattr(head, "uf_origem", None) if hasattr(head, "uf_origem") else (head.get("uf_origem") if isinstance(head, dict) else None)
    uf_destino = getattr(head, "uf_destino", None) if hasattr(head, "uf_destino") else (head.get("uf_destino") if isinstance(head, dict) else None)
    uf_origem  = (uf_origem or "SP").upper()
    uf_destino = (uf_destino or "AM").upper()

    # XML em base64 para a próxima etapa (Calcular ST)
    xml_b64 = base64.b64encode(xml_bytes).decode("ascii")

    return render_template(
        "preview.html",
        head=head,
        itens=itens,
        itens_count=len(itens),
        uf_origem=uf_origem,
        uf_destino=uf_destino,
        totais=totais,
        transp=transp,
        cobr=cobr,
        duplicatas=duplicatas,
        inf_cpl=inf_cpl,
        xml_b64=xml_b64
    )


@app.route("/calcular", methods=["POST"])
def calcular():
    xml_bytes = _xml_from_request()
    if not xml_bytes:
        flash("Não foi possível recuperar o XML.")
        return redirect(url_for("index"))

    uf_origem = request.form.get("uf_origem", "SP")
    uf_destino = request.form.get("uf_destino", "AM")

    nfe = NFEXML(xml_bytes)
    itens = nfe.itens()

    linhas = []
    total_st = 0.0

    for it in itens:
        r = motor.calcula_st(it, uf_origem, uf_destino, usar_multiplicador=True)

        p = r.memoria.get("parametros", {})
        ali_int = float(p.get("ALI_INT", 0.18))

        # <<< aceita as duas grafias
        mva_percent = float(
            r.memoria.get("MARGEM_DE_VALOR_AGREGADO_MVA",
                          r.memoria.get("MARGEM DE VALOR AGREGADO - MVA", 0.0))
        )
        venda_desc = float(
            r.memoria.get("venda_desc_icms",
                          r.memoria.get("VALOR DA VENDA COM DESCONTO DE ICMS", 0.0))
        )
        base_st = float(
            r.memoria.get("BASE_ST",
                          r.memoria.get("BASE DE CÁLCULO SUBSTITUIÇÃO TRIBUTÁRIA", 0.0))
        )
        valor_agregado = float(
            r.memoria.get("VALOR_AGREGADO",
                          r.memoria.get("VALOR AGREGADO", 0.0))
        )
        valor_icms_st = float(
            r.memoria.get("VALOR_ICMS_ST",
                          r.memoria.get("VALOR DO ICMS ST", 0.0))
        )
        saldo_devedor = float(
            r.memoria.get("SALDO_DEVEDOR_ST",
                          r.memoria.get("VALOR SALDO DEVEDOR ICMS ST", 0.0))
        )

        # multiplicador sem truncar (virá como 0.1947)
        mult = float(
            r.memoria.get("MULT_SEFAZ",
                          r.memoria.get("MULTIPLICADOR SEFAZ", p.get("ALI_INTER", 0.0)))
        )

        # ICMS Retido: prioridade p/ memória; senão mult * venda_desc; fallback saldo
        icms_ret_mem = r.memoria.get("VALOR ICMS RETIDO") or r.memoria.get("ICMS_RETIDO")
        if icms_ret_mem is not None:
            icms_retido = round(float(icms_ret_mem), 2)
        else:
            icms_ret_calc = round(mult * venda_desc, 2) if (mult and venda_desc) else 0.0
            icms_retido = icms_ret_calc if icms_ret_calc > 0 else round(saldo_devedor, 2)

        total_st += icms_retido

        linhas.append({
            # identificação
            "idx": it.nItem,
            "cProd": it.cProd,
            "xProd": it.xProd,
            "ncm": it.ncm,
            "cst": it.cst,
            "cfop": it.cfop,

            # valores básicos
            "qCom": float(it.qCom),
            "vUnCom": float(it.vUnCom),
            "vProd": float(it.vProd),
            "vFrete": float(it.vFrete),
            "vIPI": float(it.vIPI),
            "vOutro": float(it.vOutro),
            "vICMSDeson": float(
    r.memoria.get("ICMS DESONERADO", r.memoria.get("icms_deson", getattr(it, "vICMSDeson", 0.0)))
),

            # colunas iguais à planilha
            "venda_desc_icms": venda_desc,
            "valor_operacao": venda_desc,              # na sua planilha são iguais
            "mva_percentual": mva_percent,             # %
            "valor_agregado": valor_agregado,
            "base_st": base_st,
            "aliq_st": ali_int,                        # fração (exibir % no template)
            "valor_icms_st": valor_icms_st,            # Base ST * Aliq interna
            "saldo_devedor": saldo_devedor,
            "multiplicador": mult,                     # fração (exibir %)
            "icms_retido": icms_retido,
        })

    return render_template(
        "resultado.html",
        linhas=linhas,
        total_st=total_st,
        uf_origem=uf_origem,
        uf_destino=uf_destino
    )


@app.route("/admin/run-update")
def run_update():
    """Executa o updater para AM e recarrega parâmetros."""
    uf = request.args.get("uf", "AM").upper()
    if uf == "AM":
        run_update_am(sheet_client)
        _reload_params()
        flash("Atualização AM executada e parâmetros recarregados.", "success")
    else:
        flash(f"UF não suportada ainda: {uf}", "warning")
    return redirect(url_for("index"))

@app.route("/admin/reload")
def admin_reload():
    """Recarrega parâmetros do Google Sheets sem rodar o updater."""
    _reload_params()
    flash("Parâmetros recarregados do Google Sheets.", "info")
    return redirect(url_for("index"))

@app.route("/config", methods=["GET"])
def config_view():
    df_sources = matrices.get("sources")
    if df_sources is None or df_sources.empty:
        df_sources = pd.DataFrame(
            columns=["ATIVO", "UF", "NOME", "URL", "TIPO", "PARSER", "PRIORIDADE"]
        )
    sources = df_sources.fillna("").to_dict(orient="records")
    columns = list(df_sources.columns) if len(df_sources.columns) else ["ATIVO","UF","NOME","URL","TIPO","PARSER","PRIORIDADE"]
    return render_template("config.html", sources=sources, columns=columns)


@app.route("/config/save", methods=["POST"])
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
        sheet_client.write_df("sources", df_new)
        _reload_params()
        flash("Fontes salvas com sucesso.", "success")
    except Exception as e:
        flash(f"Falha ao salvar fontes: {e}", "danger")

    return redirect(url_for("config_view"))

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        flash("Envie um arquivo XML.", "danger")
        return redirect(url_for("index"))

    f = request.files["file"]
    if f.filename == "" or not allowed(f.filename):
        flash("Arquivo inválido. Envie uma NF-e em XML.", "danger")
        return redirect(url_for("index"))

    xml_bytes = f.read()
    try:
        nfe = NFEXML(xml_bytes)
        itens = nfe.itens()
    except Exception as e:
        flash(f"Não foi possível ler o XML: {e}", "danger")
        return redirect(url_for("index"))

    uf_origem = request.form.get("uf_origem", "SP").upper()
    uf_destino = request.form.get("uf_destino", "AM").upper()
    usar_mult = request.form.get("usar_multiplicador", "on") == "on"

    linhas = []
    total_st = 0.0
    for idx, it in enumerate(itens, start=1):
        r = motor.calcula_st(it, uf_origem, uf_destino, usar_multiplicador=usar_mult)
        m = r.memoria

        linhas.append({
            "seq": m["SEQUENCIAL ITEM"],
            "cod": m["COD. PRODUTO"],
            "desc": m["DESCRIÇÃO"],
            "ncm": m["NCM"],
            "cfop": it.cfop,
            "cst": it.cst,
            "quant": m["QUANT."],
            "vun": m["VALOR UNIT."],
            "vprod": m["VLR TOTAL PRODUTO."],
            "frete": m["FRETE"],
            "ipi": m["IPI"],
            "vout": m["DESP. ACES."],
            "icms_deson": m["ICMS DESONERADO"],
            "venda_desc_icms": m["VALOR DA VENDA COM DESCONTO DE ICMS"],
            "valor_oper": m["VALOR DA OPERAÇÃO"],
            "mva_tipo": m["mva_tipo"],
            "mva_percent": m["MARGEM DE VALOR AGREGADO - MVA"],
            "valor_agregado": m["VALOR AGREGADO"],
            "base_st": m["BASE DE CÁLCULO SUBSTITUIÇÃO TRIBUTÁRIA"],
            "aliq_st": m["ALÍQUOTA ICMS-ST"],  # decimal
            "icms_teorico_dest": m["icms_teorico_dest"],
            "icms_origem_calc": m["icms_origem_calc"],
            "icms_st": m["VALOR DO ICMS ST"],
            "saldo_devedor": m["VALOR SALDO DEVEDOR ICMS ST"],
            "mult_sefaz": m["MULTIPLICADOR SEFAZ"],  # fator
            "icms_retido": m["VALOR ICMS RETIDO"],
        })
        total_st += float(r.icms_st_devido)

    payload = {
        "uf_origem": uf_origem,
        "uf_destino": uf_destino,
        "linhas": linhas,
        "total_st": total_st,
    }
    payload_json = json.dumps(payload)

    return render_template(
        "resultado.html",
        linhas=linhas,
        total_st=total_st,
        uf_origem=uf_origem,
        uf_destino=uf_destino,
        payload_json=payload_json
    )

@app.route("/exportar-pdf", methods=["POST"])
def exportar_pdf():
    data_json = request.form.get("data")
    if not data_json:
        flash("Dados ausentes para gerar o PDF.", "danger")
        return redirect(url_for("index"))
    data = data_json
    try:
        cnt = 0
        while isinstance(data, str) and cnt < 3:
            data = json.loads(data)
            cnt += 1
    except Exception as e:
        flash(f"Payload inválido para PDF: {e}", "danger")
        return redirect(url_for("index"))

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
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="memoria_calculo_icms.pdf"
    )

# Diagnóstico opcional
@app.route("/debug/sheets")
def debug_sheets():
    try:
        info = {
            "service_email": sheet_client.service_email,
            "spreadsheet_title": sheet_client.sh.title,
            "worksheets": [ws.title for ws in sheet_client.sh.worksheets()],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        return jsonify(info), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
