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
    """Recarrega as planilhas e o motor após uma atualização."""
    global matrices, motor
    matrices = sheet_client.matrices()
    motor = MotorCalculo(matrices)

# ---------------------------------------
# Agendador mensal (dia 1 às 03:00)
# ---------------------------------------
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(lambda: run_update_am(sheet_client), "cron", day=1, hour=3, minute=0)
scheduler.start()

# ---------------------------------------
# Rotas
# ---------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/calcular", methods=["POST"])
def calcular():
    xml_bytes = _xml_from_request()
    if not xml_bytes:
        flash("Não foi possível recuperar o XML.")
        return redirect(url_for("index"))

    nfe = NFEXML(xml_bytes)
    itens = nfe.itens()

    uf_origem = request.form.get("uf_origem", "SP")
    uf_destino = request.form.get("uf_destino", "AM")
    usar_mult = request.form.get("usar_multiplicador", "on") == "on"

    linhas = []
    total_st = 0.0
    for it in itens:
        r = motor.calcula_st(it, uf_origem, uf_destino, usar_multiplicador=usar_mult)
        m = r.memoria
        linhas.append({
            "seq": m["SEQUENCIAL ITEM"],
            "cod": m["COD. PRODUTO"],
            "desc": m["DESCRIÇÃO"],
            "ncm":  m["NCM"],
            "cfop": it.cfop,
            "cst":  it.cst,
            "quant": m["QUANT."],
            "vun":   m["VALOR UNIT."],
            "vprod": m["VLR TOTAL PRODUTO."],
            "frete": m["FRETE"],
            "ipi":   m["IPI"],
            "vout":  m["DESP. ACES."],
            "icms_deson": m["ICMS DESONERADO"],
            "venda_desc_icms": m["VALOR DA VENDA COM DESCONTO DE ICMS"],
            "valor_oper":      m["VALOR DA OPERAÇÃO"],
            "mva_tipo":        m["mva_tipo"],
            "mva_percent":     m["MARGEM DE VALOR AGREGADO - MVA"],
            "valor_agregado":  m["VALOR AGREGADO"],
            "base_st":         m["BASE DE CÁLCULO SUBSTITUIÇÃO TRIBUTÁRIA"],
            "aliq_st":         m["ALÍQUOTA ICMS-ST"],         # decimal
            "icms_teorico_dest": m["icms_teorico_dest"],
            "icms_origem_calc":  m["icms_origem_calc"],
            "icms_st":         m["VALOR DO ICMS ST"],
            "saldo_devedor":   m["VALOR SALDO DEVEDOR ICMS ST"],
            "mult_sefaz":      m["MULTIPLICADOR SEFAZ"],      # fator
            "icms_retido":     m["VALOR ICMS RETIDO"],
        })
        total_st += r.icms_st_devido

    payload = {
        "uf_origem": uf_origem,
        "uf_destino": uf_destino,
        "linhas": linhas,
        "total_st": total_st,
    }
    payload_json = json.dumps(payload)

    return render_template("resultado.html",
                           linhas=linhas,
                           total_st=total_st,
                           uf_origem=uf_origem,
                           uf_destino=uf_destino,
                           payload_json=payload_json)

# -------- NOVA rota: preview bonitinho --------
@app.route("/preview", methods=["POST"])
def preview():
    # Aceita 'file' ou 'xml' como nome do input
    f = request.files.get("file") or request.files.get("xml")
    if not f:
        flash("Nenhum arquivo foi enviado (campo 'file' ou 'xml').", "warning")
        return redirect(url_for("index"))

    if f.filename == "":
        flash("Arquivo sem nome. Escolha um XML válido.", "warning")
        return redirect(url_for("index"))

    if not allowed(f.filename):
        flash("Extensão inválida. Envie um arquivo .xml de NF-e.", "warning")
        return redirect(url_for("index"))

    try:
        xml_bytes = f.read()
        if not xml_bytes:
            flash("Arquivo está vazio.", "warning")
            return redirect(url_for("index"))

        # Parse do XML
        nfe = NFEXML(xml_bytes)
        head = nfe.header()  # ex.: {'uf_origem': 'SP', 'uf_destino': 'AM'}
        itens = nfe.itens()

        # Vamos mostrar um preview com os campos básicos que você quer ver
        linhas = []
        for it in itens:
            linhas.append({
                "seq": getattr(it, "nItem", 0),
                "cod": getattr(it, "cProd", ""),
                "desc": getattr(it, "xProd", ""),
                "ncm": getattr(it, "ncm", ""),
                "cfop": getattr(it, "cfop", ""),
                "cst": getattr(it, "cst", ""),
                "quant": float(getattr(it, "qCom", 0.0)),
                "vun":   float(getattr(it, "vUnCom", 0.0)),
                "vprod": float(getattr(it, "vProd", 0.0)),
                "frete": float(getattr(it, "vFrete", 0.0)),
                "ipi":   float(getattr(it, "vIPI", 0.0)),
                "vout":  float(getattr(it, "vOutro", 0.0)),
                "vdesc": float(getattr(it, "vDesc", 0.0)),
                "icms_deson": float(getattr(it, "vICMSDeson", 0.0)),
            })

        # Para o botão "Calcular", precisamos mandar o XML de volta.
        # Serializamos em base64 para um <input type="hidden"> no preview.html.
        import base64
        xml_b64 = base64.b64encode(xml_bytes).decode("ascii")

        return render_template(
            "preview.html",
            head=head,
            linhas=linhas,
            xml_b64=xml_b64
        )
    except Exception as e:
        # Loga no console e volta pra index com aviso
        app.logger.exception("Falha no preview")
        flash(f"Não foi possível ler o XML: {e}", "danger")
        return redirect(url_for("index"))

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
    """
    Página de configuração: mostra e permite editar a aba 'sources'.
    """
    df_sources = matrices.get("sources")
    if df_sources is None or df_sources.empty:
        # estrutura mínima sugerida
        df_sources = pd.DataFrame(
            columns=["ATIVO", "UF", "NOME", "URL", "TIPO", "PARSER", "PRIORIDADE"]
        )
    sources = df_sources.fillna("").to_dict(orient="records")
    columns = list(df_sources.columns) if len(df_sources.columns) else ["ATIVO","UF","NOME","URL","TIPO","PARSER","PRIORIDADE"]
    return render_template("config.html", sources=sources, columns=columns)


@app.route("/config/save", methods=["POST"])
def config_save():
    """
    Salva as edições da tabela 'sources' no Google Sheets.
    """
    # Pegamos o cabeçalho (lista de colunas) vindo do form
    cols = request.form.getlist("cols[]")
    # As linhas chegam em blocos tipo row-0-<COL>, row-1-<COL>...
    # Vamos descobrir quantas linhas existem olhando por um campo obrigatório (ex.: UF)
    # Melhor: o front manda row_count
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
        # só guarda a linha se tiver algo preenchido (ex.: URL ou NOME)
        if any(row):
            rows.append(row)

    # Monta DataFrame e grava
    import pandas as pd
    df_new = pd.DataFrame(rows, columns=cols)

    # Coerções leves (opcional)
    if "ATIVO" in df_new.columns:
        df_new["ATIVO"] = df_new["ATIVO"].apply(lambda x: "1" if str(x).strip() in ("1","true","True","on","ON") else "0")
    if "PRIORIDADE" in df_new.columns:
        df_new["PRIORIDADE"] = df_new["PRIORIDADE"].apply(lambda x: str(x).strip() if str(x).strip().isdigit() else "")

    try:
        sheet_client.write_df("sources", df_new)
        # recarrega matrices para refletir alteração
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
        total_st += r.icms_st_devido

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
                "mva_percentual_aplicado": row.get("mva_percentual", 0.0),  # << NOVO
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
