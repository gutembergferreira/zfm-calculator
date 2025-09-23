from datetime import datetime
from typing import List, Tuple
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from reportlab.pdfgen.canvas import Canvas

from calc import ItemNF, ResultadoItem

LOGO_PATH = os.path.join("static", "logo.png")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Heading1"], fontSize=16, leading=20, spaceAfter=8),
        "label": ParagraphStyle("label", parent=base["Normal"], fontSize=9, leading=12, textColor=colors.grey),
        "value": ParagraphStyle("value", parent=base["Normal"], fontSize=10, leading=12),
        "value_bold": ParagraphStyle("value_bold", parent=base["Normal"], fontSize=10, leading=12, fontName="Helvetica-Bold"),
        "total": ParagraphStyle("total", parent=base["Heading3"], fontSize=12, leading=14, spaceBefore=6),
    }


def _fmt(v: float) -> str:
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"


def _footer(canvas: Canvas, doc):
    w, h = A4
    y = 12 * mm
    canvas.setStrokeColor(colors.lightgrey)
    canvas.setLineWidth(0.5)
    canvas.line(15 * mm, y + 6 * mm, w - 15 * mm, y + 6 * mm)
    if os.path.exists(LOGO_PATH):
        try:
            canvas.drawImage(LOGO_PATH, 15 * mm, y, width=20 * mm, height=8 * mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    canvas.setFont("Helvetica", 8)
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    canvas.drawRightString(w - 15 * mm, y + 2 * mm, f"Gerado em {ts}  •  Página {doc.page}")


def _title(uf_origem: str, uf_destino: str):
    st = _styles()
    return Paragraph(
        f"Memória de Cálculo ICMS-ST — Origem <b>{uf_origem}</b> → Destino <b>{uf_destino}</b>",
        st["title"],
    )


def _item_block(idx: int, it: ItemNF, r: ResultadoItem) -> Table:
    st = _styles()
    percent = float(r.memoria.get("mva_percentual_aplicado", 0.0))
    modo = str(r.memoria.get("mva_tipo", "-"))

    head = [
        Paragraph("Item", st["label"]), Paragraph(str(idx), st["value"]),
        Paragraph("NCM", st["label"]), Paragraph(it.ncm or "-", st["value"]),
        Paragraph("CFOP", st["label"]), Paragraph(it.cfop or "-", st["value"]),
        Paragraph("CST", st["label"]), Paragraph(it.cst or "-", st["value"]),
    ]

    l1 = [
        Paragraph("Base oper.", st["label"]),
        Paragraph(_fmt(r.memoria.get("base_oper", 0.0)), st["value"]),
        Paragraph("MVA", st["label"]),
        Paragraph(f"{modo} ({percent:.2f}%)", st["value"]),  # <<< mostra o percentual
        Paragraph("Base ST", st["label"]),
        Paragraph(_fmt(r.base_calculo_st), st["value"]),
    ]

    l2 = [
        Paragraph("ICMS teórico destino", st["label"]),
        Paragraph(_fmt(r.memoria.get("icms_teorico_dest", 0.0)), st["value"]),
        Paragraph("ICMS origem (calc)", st["label"]),
        Paragraph(_fmt(r.memoria.get("icms_origem_calc", 0.0)), st["value"]),
        Paragraph("ICMS-ST devido", st["label"]),
        Paragraph(_fmt(r.icms_st_devido), st["value_bold"]),
    ]

    table = Table([head, l1, l2],
                  colWidths=[18*mm, 20*mm, 18*mm, 25*mm, 18*mm, 20*mm, 18*mm, 20*mm])

    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("LINEBEFORE", (0, 0), (0, -1), 0.25, colors.lightgrey),
        ("LINEAFTER", (-1, 0), (-1, -1), 0.25, colors.lightgrey),
        ("GRID", (0, 1), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def gerar_pdf(resultados: List[Tuple[ItemNF, ResultadoItem]], uf_origem: str, uf_destino: str) -> bytes:
    from io import BytesIO
    buff = BytesIO()

    doc = SimpleDocTemplate(
        buff,
        pagesize=A4,
        leftMargin=15*mm,
        rightMargin=15*mm,
        topMargin=18*mm,
        bottomMargin=18*mm,
        title="Memória de Cálculo ICMS-ST",
    )

    story = []
    story.append(_title(uf_origem, uf_destino))
    story.append(Spacer(1, 4*mm))

    total = 0.0
    for i, (it, r) in enumerate(resultados, start=1):
        story.append(_item_block(i, it, r))
        story.append(Spacer(1, 5*mm))
        total += float(getattr(r, "icms_st_devido", 0.0))

    st = _styles()
    story.append(Paragraph(f"Total ICMS-ST: <b>R$ {_fmt(total)}</b>", st["total"]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf = buff.getvalue()
    buff.close()
    return pdf
