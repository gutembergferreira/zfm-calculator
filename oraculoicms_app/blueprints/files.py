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
bp = Blueprint("files", __name__)

ALLOWED = {'.xml', '.XML'}

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
    if not file:
        flash("Selecione um arquivo XML.", "warning")
        return redirect(url_for("files.list_files"))
    ext = os.path.splitext(file.filename)[1]
    if ext not in ALLOWED:
        flash("Formato inválido. Envie apenas arquivos .xml", "danger")
        return redirect(url_for("files.list_files"))
    user = current_user()
    user_root = user_upload_root(user.id)
    safe_name = secure_filename(file.filename)
    target = user_root / safe_name
    file.save(str(target))
    size = target.stat().st_size
    ok, msg = _enforce_plan_limits(user, size_add=size)
    if not ok:
        target.unlink(missing_ok=True)
        flash(msg, "danger")
        return redirect(url_for("files.list_files"))
    rec = UserFile(user_id=user.id, filename=safe_name, storage_path=str(target), size_bytes=size, md5=_md5(target))
    quota = _get_quota(user.id)
    quota.files_count += 1
    quota.storage_bytes += size
    quota.month_uploads += 1
    db.session.add(quota)
    db.session.add(rec); db.session.commit()
    db.session.add(AuditLog(user_id=user.id, action="upload", ref=f"user_file:{rec.id}", description=safe_name)); db.session.commit()
    flash("Upload concluído e arquivo salvo.", "success")
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

    # Parse (usa seu xml_parser.NFEXML)
    parser = NFEXML(xml_bytes)
    try:
        head = parser.header() or {}
    except Exception:
        head = {}
    try:
        totais = parser.totais() or {}
    except Exception:
        totais = {}
    try:
        itens = parser.itens() or []
    except Exception:
        itens = []

    # IMPORTANTE: enviar SEMPRE esses nomes que o template usa
    return render_template(
        "preview.html",
        filename=uf.filename,
        head=head,
        totais=totais,
        itens=itens,
        xml=xml_str,         # se seu preview mostra o XML bruto em algum tab
    )


@bp.route("/deletar-xml/<int:file_id>", methods=["POST"])
@login_required
def deletar_xml(file_id:int):
    uf = UserFile.query.filter_by(id=file_id, user_id=current_user().id, deleted_at=None).first_or_404()
    uf.deleted_at = datetime.datetime.utcnow()
    size = uf.size_bytes or 0
    uf.deleted_at = datetime.datetime.utcnow()
    db.session.add(uf)
    quota = _get_quota(current_user().id)
    quota.files_count = max(0, (quota.files_count or 0) - 1)
    quota.storage_bytes = max(0, (quota.storage_bytes or 0) - size)
    db.session.add(quota)
    db.session.add(uf); db.session.commit()
    db.session.add(AuditLog(user_id=current_user().id, action="delete", ref=f"user_file:{uf.id}", description=uf.filename)); db.session.commit()
    flash("Arquivo removido do seu espaço.", "info")
    return redirect(url_for("files.list_files"))

@bp.route("/parse-xml/<int:file_id>", methods=["POST"])
@login_required
def parse_xml(file_id:int):
    uf = UserFile.query.filter_by(id=file_id, user_id=current_user().id, deleted_at=None).first_or_404()
    xml_bytes = Path(uf.storage_path).read_bytes()
    parser = NFEXML(xml_bytes)
    head = parser.header() or {}
    tot = parser.totais() or {}
    chave = head.get('chave')
    # Já existe resumo desta chave para ESTE usuário?
    dup = (db.session.query(NFESummary)
           .join(UserFile, NFESummary.user_file_id == UserFile.id)
           .filter(UserFile.user_id == current_user().id, NFESummary.chave == chave)
           .first())
    if dup:
        flash(f"NF-e {chave} já foi processada (arquivo #{dup.user_file_id}).", "info")
        return redirect(url_for("files.list_files"))
    # Persist
    s = NFESummary.query.filter_by(user_file_id=uf.id).first()
    if not s:
        s = NFESummary(user_file_id=uf.id)
    from datetime import datetime as _dt
    emissao_iso = head.get('dhEmi')
    try:
        emissao_dt = _dt.fromisoformat(emissao_iso.replace('Z','').replace('T',' ')) if emissao_iso else None
    except Exception:
        emissao_dt = None
    s.chave = head.get('chave')
    s.emit_cnpj = head.get('emitente_cnpj')
    s.dest_cnpj = head.get('destinatario_cnpj')
    s.emit_nome = head.get('emitente_nome')
    s.dest_nome = head.get('destinatario_nome')
    s.numero = head.get('numero')
    s.serie = head.get('serie')
    s.emissao = emissao_dt
    s.valor_total = tot.get('vNF', 0.0)
    s.valor_produtos = tot.get('vProd', 0.0)
    s.icms = tot.get('vICMS', 0.0)
    s.icms_st = tot.get('vST', 0.0)
    s.ipi = tot.get('vIPI', 0.0)
    # PIS/COFINS não aparecem nos totais agregados em todas as versões — manter 0 se não disponível
    s.pis = 0.0
    s.cofins = 0.0
    # meta_json: salve header+totais
    meta = {'header': head, 'totais': tot}
    s.meta_json = json.dumps(meta, ensure_ascii=False)
    db.session.add(s); db.session.commit()
    db.session.add(AuditLog(user_id=current_user().id, action="parse", ref=f"user_file:{uf.id}", description=uf.filename)); db.session.commit()
    flash("XML processado e resumo salvo.", "success")
    return redirect(url_for("files.list_files"))

@bp.route("/relatorios/nfe")
@login_required
def relatorio_nfe():
    # Filtros simples por período (mês atual por padrão)
    from sqlalchemy import func
    start = request.args.get("start")
    end = request.args.get("end")
    if not start or not end:
        now = datetime.datetime.utcnow()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # próximo mês - 1s
        nxt = (start + datetime.timedelta(days=32)).replace(day=1)
        end = nxt
    else:
        start = datetime.datetime.fromisoformat(start)
        end = datetime.datetime.fromisoformat(end)
    rows = db.session.query(NFESummary).join(UserFile, NFESummary.user_file_id==UserFile.id)\
        .filter(UserFile.user_id==current_user().id, NFESummary.emissao>=start, NFESummary.emissao<end)\
        .order_by(NFESummary.emissao.desc()).all()
    # Agregações
    tot_notas = len(rows)
    soma_total = sum([float(r.valor_total or 0) for r in rows])
    soma_icms = sum([float(r.icms or 0) for r in rows])
    soma_st = sum([float(r.icms_st or 0) for r in rows])
    return render_template("relatorio_geral.html", rows=rows, tot_notas=tot_notas, soma_total=soma_total, soma_icms=soma_icms, soma_st=soma_st, start=start, end=end)
