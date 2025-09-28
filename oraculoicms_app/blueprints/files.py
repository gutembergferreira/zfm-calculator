# oraculoicms_app/blueprints/files.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, hashlib, datetime, json
from pathlib import Path
from flask import Blueprint, current_app, request, render_template, redirect, url_for, flash, send_file, abort, session
from werkzeug.utils import secure_filename
from oraculoicms_app.decorators import login_required
from oraculoicms_app.extensions import db
from oraculoicms_app.models.user import User
from oraculoicms_app.models.plan import Plan
from oraculoicms_app.models.file import UserFile, NFESummary, AuditLog
from xml_parser import NFEXML
from oraculoicms_app.models.user_quota import UserQuota
from base64 import b64encode
from xml.etree import ElementTree as ET
from .nfe_indexer import upsert_summary_from_xml
bp = Blueprint("files", __name__)

ALLOWED = {'.xml', '.XML'}

def _is_nfe_xml(xml_bytes: bytes) -> tuple[bool, str]:
    """
    Validações rápidas:
    - XML parseável
    - Root <NFe> ou <nfeProc> contendo <NFe>
    - Presença de <infNFe Id="..."> e de campos da seção <ide> (nNF/serie/UF etc.)
    """
    try:
        # tenta detectar encoding a partir do prólogo
        txt = xml_bytes.decode("utf-8", errors="ignore")
        root = ET.fromstring(txt)
    except Exception:
        return False, "Arquivo não é um XML válido."

    tag = root.tag.lower()
    # namespaces virão no tag como {ns}nfeproc – normalize checando término
    if tag.endswith("nfe"):
        nfe = root
    elif tag.endswith("nfeproc"):
        nfe = None
        for child in root:
            if child.tag.lower().endswith("nfe"):
                nfe = child
                break
        if nfe is None:
            return False, "Estrutura nfeProc sem o nó NFe."
    else:
        return False, "XML não parece ser de NF-e (root != NFe/nfeProc)."

    # procurar infNFe
    inf = None
    for child in nfe:
        if child.tag.lower().endswith("infnfe"):
            inf = child
            break
    if inf is None:
        return False, "NF-e sem nó infNFe."

    # checar alguns campos de ide
    ide = None
    for child in inf:
        if child.tag.lower().endswith("ide"):
            ide = child
            break
    if ide is None:
        return False, "NF-e sem seção <ide>."

    # pelo menos um destes deve existir
    campos_ok = {"cuf","nnf","serie","mod","cmunfg"}
    encontrados = set()
    for c in ide:
        encontrados.add(c.tag.split("}",1)[-1].lower())
    if not (campos_ok & encontrados):
        return False, "NF-e sem campos mínimos em <ide>."

    return True, ""

def _get_quota(user_id:int) -> UserQuota:
    q = UserQuota.query.filter_by(user_id=user_id).first()
    if not q:
        q = UserQuota(user_id=user_id)
        db.session.add(q); db.session.commit()
    # garante rollover mensal
    from datetime import datetime
    cur = datetime.utcnow().strftime("%Y-%m")
    if q.month_ref != cur:
        q.month_ref = cur
        q.month_uploads = 0
        # se desejar, zere também storage mensal (se adicionar esse campo)
        db.session.add(q); db.session.commit()
    return q

def current_user():
    data = session.get("user")
    if not data:
        return None
    email = data.get("email")
    if not email:
        return None
    return User.query.filter_by(email=email).first()


def user_upload_root(user_id:int) -> Path:
    root = Path(current_app.config.get("UPLOAD_FOLDER", "./uploads"))
    user_root = root / f"user_{user_id}" / datetime.datetime.utcnow().strftime("%Y/%m")
    user_root.mkdir(parents=True, exist_ok=True)
    return user_root

def _md5(fp:Path) -> str:
    h = hashlib.md5()
    with open(fp, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def _enforce_plan_limits(user, size_add:int) -> tuple[bool,str]:
    plan = Plan.query.filter_by(slug=user.plan).first() if hasattr(user, 'plan') else None
    if not plan:
        return True, ""
    quota = _get_quota(user.id)

    # limites absolutos
    if plan.max_files and (quota.files_count + 1) > plan.max_files:
        return False, f"Limite de arquivos simultâneos excedido ({quota.files_count}/{plan.max_files})."

    if plan.max_storage_mb and (quota.storage_bytes + size_add) > plan.max_storage_mb * 1024 * 1024:
        used_mb = round(quota.storage_bytes/1048576,1)
        return False, f"Limite de armazenamento do plano excedido ({used_mb}MB/{plan.max_storage_mb}MB)."

    # limites mensais
    if plan.max_monthly_files and (quota.month_uploads + 1) > plan.max_monthly_files:
        return False, f"Limite mensal de uploads excedido ({quota.month_uploads}/{plan.max_monthly_files})."

    # se quiser controlar MB mensal, crie um campo month_storage_bytes no UserQuota
    # e valide aqui de forma análoga.

    return True, ""

def _get_summary_owned(file_id:int):
    uf = UserFile.query.filter_by(id=file_id, user_id=current_user().id, deleted_at=None).first_or_404()
    s = NFESummary.query.filter_by(user_file_id=uf.id).first_or_404()
    return uf, s

@bp.route("/ver-calculo/<int:file_id>")
@login_required
def ver_calculo(file_id:int):
    uf, s = _get_summary_owned(file_id)

    if not s or not s.processed_at:
        flash("Este XML ainda não foi processado.", "warning")
        return redirect(url_for("files.list_files"))

    if not s.calc_json:
        flash("Ainda não há cálculo salvo para esta NF. Abra o preview e clique em “Calcular ST”.", "info")
        return redirect(url_for("files.preview_xml", file_id=file_id))

    try:
        payload = json.loads(s.calc_json)
    except Exception:
        flash("Não foi possível carregar o cálculo salvo.", "danger")
        return redirect(url_for("files.list_files"))

    linhas     = payload.get("linhas", [])
    total_st   = float(payload.get("total_st", 0))
    uf_origem  = payload.get("uf_origem", "SP")
    uf_destino = payload.get("uf_destino", "AM")

    return render_template(
        "resultado.html",
        linhas=linhas,
        total_st=total_st,
        uf_origem=uf_origem,
        uf_destino=uf_destino,
        payload_json=json.dumps(payload, ensure_ascii=False)
    )

@bp.route("/marcar-status/<int:file_id>/<status>", methods=["POST"])
@login_required
def marcar_status(file_id:int, status:str):
    _, s = _get_summary_owned(file_id)
    status = status.lower()
    if status not in ("pending","conforme","nao_conforme"):
        abort(400)
    s.validation_status = status
    db.session.add(s); db.session.commit()
    flash(f"NF marcada como {status.replace('_',' ')}.", "success")
    return redirect(url_for("files.list_files"))

@bp.route("/toggle-incluir/<int:file_id>", methods=["POST"])
@login_required
def toggle_incluir(file_id:int):
    _, s = _get_summary_owned(file_id)
    s.include_in_totals = not bool(s.include_in_totals)
    db.session.add(s); db.session.commit()
    flash("Preferência de inclusão nos totais atualizada.", "success")
    return redirect(url_for("files.list_files"))


@bp.route("/meus-arquivos", methods=["GET"])
@login_required
def list_files():
    q = UserFile.query.filter_by(user_id=current_user().id, deleted_at=None).order_by(UserFile.uploaded_at.desc())
    files = q.limit(200).all()
    return render_template("files.html", files=files)

@bp.route("/upload-xml", methods=["POST"])
@login_required
def upload_xml():
    file = request.files.get("xml")
    display_name = (request.form.get("display_name") or "").strip()

    if not file:
        flash("Selecione um arquivo XML.", "warning")
        return redirect(url_for("files.list_files"))

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED:
        flash("Formato inválido. Envie apenas arquivos .xml", "danger")
        return redirect(url_for("files.list_files"))

    # 1) Lê os bytes do upload
    data = file.read()
    if not data:
        flash("Arquivo vazio.", "danger")
        return redirect(url_for("files.list_files"))

    # 2) PRÉ-VALIDAÇÃO: é uma NF-e mesmo?
    ok, err = _is_nfe_xml(data)
    if not ok:
        flash(f"Upload recusado: {err}", "danger")
        return redirect(url_for("files.list_files"))

    # 3) Valida limites do plano com base no tamanho real
    user = current_user()
    size = len(data)
    ok, msg = _enforce_plan_limits(user, size_add=size)
    if not ok:
        flash(msg, "danger")
        return redirect(url_for("files.list_files"))

    # 4) Caminho do usuário e filename seguro/único
    user_root = user_upload_root(user.id)
    safe_name = secure_filename(file.filename)
    target = user_root / safe_name
    # evita sobrescrever: se já existir, adiciona sufixo numérico
    if target.exists():
        stem, ext = os.path.splitext(safe_name)
        i = 2
        while True:
            candidate = user_root / f"{stem} ({i}){ext}"
            if not candidate.exists():
                target = candidate
                safe_name = candidate.name
                break
            i += 1

    # 5) Salva no disco
    with open(target, "wb") as fh:
        fh.write(data)

    # 6) Registros no banco (md5, display_name fallback)
    md5 = _md5(target)  # ou calcule por data: hashlib.md5(data).hexdigest()
    rec = UserFile(
        user_id=user.id,
        filename=safe_name,
        storage_path=str(target),
        size_bytes=size,
        md5=md5,
        display_name=display_name or os.path.splitext(safe_name)[0]
    )

    # 7) Atualiza quota
    quota = _get_quota(user.id)
    quota.files_count += 1
    quota.storage_bytes += size
    quota.month_uploads += 1

    db.session.add(quota)
    db.session.add(rec)
    db.session.commit()

    db.session.add(AuditLog(user_id=user.id, action="upload", ref=f"user_file:{rec.id}", description=safe_name))
    db.session.commit()

    flash("Upload concluído e arquivo validado como NF-e.", "success")
    return redirect(url_for("files.list_files"))


@bp.route("/ver-xml/<int:file_id>")
@login_required
def ver_xml(file_id:int):
    uf = UserFile.query.filter_by(id=file_id, user_id=current_user().id, deleted_at=None).first_or_404()
    p = Path(uf.storage_path)
    if not p.is_file():
        current = current_app.config.get("UPLOAD_FOLDER")
        flash(f"Arquivo não encontrado no disco. Verifique UPLOAD_FOLDER atual ({current}) e o caminho salvo: {uf.storage_path}", "danger")
        abort(404)
    return send_file(str(p), as_attachment=False, download_name=uf.filename)

@bp.route("/preview-xml/<int:file_id>")
@login_required
def preview_xml(file_id:int):
    uf = UserFile.query.filter_by(id=file_id, user_id=current_user().id, deleted_at=None).first_or_404()
    p = Path(uf.storage_path)
    if not p.is_file():
        flash("Arquivo não encontrado no disco.", "danger")
        abort(404)

    xml_bytes = p.read_bytes()
    xml_str = xml_bytes.decode("utf-8", errors="ignore")

    parser = NFEXML(xml_bytes)
    head = parser.header() or {}
    totais = parser.totais() or {}
    itens = parser.itens() or []

    xml_b64 = b64encode(xml_bytes).decode("ascii")  # <<--- ESSENCIAL!

    return render_template(
        "preview.html",
        filename=uf.filename,
        head=head,
        totais=totais,
        itens=itens,
        xml=xml_str,          # opcional (aba “Fonte”)
        xml_b64=xml_b64       # <<--- ENVIE ISTO PARA O FORM “Calcular ST”
    )


@bp.route("/deletar-xml/<int:file_id>", methods=["POST"])
@login_required
def deletar_xml(file_id:int):
    uf = UserFile.query.filter_by(id=file_id, user_id=current_user().id, deleted_at=None).first_or_404()

    # apaga resumo (se existir)
    from oraculoicms_app.models.file import NFESummary
    s = NFESummary.query.filter_by(user_file_id=uf.id).first()
    if s:
        db.session.delete(s)

    # (opcional) remover arquivo do disco:
    try:
        Path(uf.storage_path).unlink(missing_ok=True)
    except Exception:
        pass

    # marca o arquivo como deletado
    uf.deleted_at = datetime.datetime.utcnow()
    db.session.add(uf)

    # quota (se estiver usando UserQuota)
    try:
        quota = _get_quota(current_user().id)
        size = uf.size_bytes or 0
        quota.files_count = max(0, (quota.files_count or 0) - 1)
        quota.storage_bytes = max(0, (quota.storage_bytes or 0) - size)
        db.session.add(quota)
    except Exception:
        pass

    # auditoria
    db.session.add(AuditLog(user_id=current_user().id, action="delete", ref=f"user_file:{uf.id}", description=uf.filename))

    db.session.commit()
    flash("Arquivo e resumo removidos.", "info")
    return redirect(url_for("files.list_files"))


@bp.route("/parse-xml/<int:file_id>", methods=["POST"])
@login_required
def parse_xml(file_id: int):
    uf = UserFile.query.filter_by(
        id=file_id, user_id=current_user().id, deleted_at=None
    ).first_or_404()

    xml_bytes = Path(uf.storage_path).read_bytes()
    parser = NFEXML(xml_bytes)
    head = parser.header() or {}
    tot  = parser.totais() or {}
    chave = head.get("chave")

    # Já existe resumo desta CHAVE para ESTE usuário?
    # Só bloqueia se for em OUTRO arquivo.
    if chave:
        dup = (
            db.session.query(NFESummary)
            .join(UserFile, NFESummary.user_file_id == UserFile.id)
            .filter(UserFile.user_id == current_user().id, NFESummary.chave == chave)
            .first()
        )
        if dup and dup.user_file_id != uf.id:
            flash(f"NF-e {chave} já foi processada (arquivo #{dup.user_file_id}).", "info")
            return redirect(url_for("files.list_files"))

    # --------- ÚNICO caminho: UPSERT ---------
    try:
        summary, created = upsert_summary_from_xml(
            db, NFEXML, NFESummary, UserFile,
            current_user().id, xml_bytes, uf.id
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Falha ao processar XML")
        flash(f"Falha ao processar XML: {e}", "danger")
        return redirect(url_for("files.list_files"))

    # Enriquecer com meta e carimbar processed_at (se ainda não houver)
    meta = {"header": head, "totais": tot}
    summary.meta_json = json.dumps(meta, ensure_ascii=False)
    if not summary.processed_at:
        import datetime
        summary.processed_at = datetime.datetime.utcnow()

    db.session.add(summary)
    db.session.commit()

    db.session.add(
        AuditLog(
            user_id=current_user().id,
            action="parse",
            ref=f"user_file:{uf.id}",
            description=uf.filename,
        )
    )
    db.session.commit()

    flash("XML processado e resumo salvo.", "success")
    return redirect(url_for("files.list_files"))


@bp.route("/relatorios/nfe")
@login_required
def relatorio_nfe():
    from sqlalchemy import func
    # período
    start = request.args.get("start")
    end = request.args.get("end")
    if not start or not end:
        now = datetime.datetime.utcnow()
        start_dt = now - datetime.timedelta(days=90)
        end_dt = now + datetime.timedelta(days=1)
    else:
        start_dt = datetime.datetime.fromisoformat(start)
        end_dt = datetime.datetime.fromisoformat(end)

    # filtros extras
    f_status = request.args.get("status")            # 'conforme' | 'nao_conforme' | 'pending' | ''(todos)
    f_proc = request.args.get("proc")                # 'processed' | 'unprocessed' | ''(todos)
    f_totais = request.args.get("in_totals")         # '1' (somente incluídas) | '0' (somente excluídas) | ''(todas)

    q = (db.session.query(NFESummary)
         .join(UserFile, NFESummary.user_file_id==UserFile.id)
         .filter(UserFile.user_id==current_user().id,
                 NFESummary.emissao>=start_dt, NFESummary.emissao<end_dt))

    if f_status in ("conforme","nao_conforme","pending"):
        q = q.filter(NFESummary.validation_status==f_status)

    if f_proc == "processed":
        q = q.filter(NFESummary.processed_at.isnot(None))
    elif f_proc == "unprocessed":
        # não tem summary → mas estamos partindo de NFESummary; então unprocessed não aparece aqui.
        # Se quiser listar não processadas, terá que LEFT JOIN em UserFile. Mantemos só processadas neste relatório.
        pass

    if f_totais == "1":
        q = q.filter(NFESummary.include_in_totals.is_(True))
    elif f_totais == "0":
        q = q.filter(NFESummary.include_in_totals.is_(False))

    rows = q.order_by(NFESummary.emissao.desc()).all()

    # dedup por chave (defensivo)
    uniq, seen = [], set()
    for r in rows:
        if r.chave in seen:
            continue
        seen.add(r.chave)
        uniq.append(r)

    # somatórios: considerar SOMENTE as NFs marcadas para entrar nos totais
    base_totais = [r for r in uniq if r.include_in_totals]
    tot_notas = len(uniq)
    soma_total = sum(float(r.valor_total or 0) for r in base_totais)
    soma_icms  = sum(float(r.icms or 0) for r in base_totais)
    soma_st    = sum(float(r.icms_st or 0) for r in base_totais)

    return render_template("relatorio_geral.html",
                           rows=uniq,
                           tot_notas=tot_notas,
                           soma_total=soma_total,
                           soma_icms=soma_icms,
                           soma_st=soma_st,
                           start=start_dt, end=end_dt,
                           f_status=f_status or "", f_proc=f_proc or "", f_totais=f_totais or "")

@bp.route("/relatorios/nfe/selecionar", methods=["POST"])
@login_required
def selecionar_totais():
    # filtros para manter o contexto ao voltar
    start = request.form.get("start"); end = request.form.get("end")
    status = request.form.get("status",""); in_totals = request.form.get("in_totals","")

    from datetime import datetime as _dt
    start_dt = _dt.fromisoformat(start) if start else None
    end_dt   = _dt.fromisoformat(end)   if end else None

    ids = set(int(x) for x in request.form.getlist("selected[]"))

    q = db.session.query(NFESummary).join(UserFile, NFESummary.user_file_id==UserFile.id)\
        .filter(UserFile.user_id==current_user().id)
    if start_dt and end_dt:
        q = q.filter(NFESummary.emissao>=start_dt, NFESummary.emissao<end_dt)

    rows = q.all()
    for r in rows:
        r.include_in_totals = (r.id in ids)
        db.session.add(r)
    db.session.commit()
    flash("Seleção aplicada aos totais.", "success")

    return redirect(url_for("files.relatorio_nfe",
                            start=start_dt.date().isoformat() if start_dt else None,
                            end=end_dt.date().isoformat() if end_dt else None,
                            status=status, in_totals=in_totals))
