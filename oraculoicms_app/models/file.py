# app/models/file.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime
from ..extensions import db

class UserFile(db.Model):
    __tablename__ = "user_files"
    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(512), nullable=False)  # caminho absoluto/relativo no FS
    size_bytes = db.Column(db.Integer, default=0)
    md5 = db.Column(db.String(32), index=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    # Relacionamentos
    user = db.relationship("User", backref=db.backref("files", lazy="dynamic"))

class NFESummary(db.Model):
    __tablename__ = "nfe_summaries"
    id = db.Column(db.Integer, primary_key=True)
    user_file_id = db.Column(db.Integer, db.ForeignKey("user_files.id"), unique=True, nullable=False)
    processed_at = db.Column(db.DateTime)  # quando processou o XML
    validation_status = db.Column(db.String(16), default="pending", index=True)  # pending|conforme|nao_conforme
    include_in_totals = db.Column(db.Boolean, default=True, index=True)
    # campos comuns de NFe
    chave = db.Column(db.String(60), index=True)
    emit_cnpj = db.Column(db.String(20), index=True)
    dest_cnpj = db.Column(db.String(20), index=True)
    emit_nome = db.Column(db.String(180))
    dest_nome = db.Column(db.String(180))
    numero = db.Column(db.String(20), index=True)
    serie = db.Column(db.String(10))
    emissao = db.Column(db.DateTime, index=True)
    valor_total = db.Column(db.Numeric(14,2), default=0)
    valor_produtos = db.Column(db.Numeric(14,2), default=0)
    icms = db.Column(db.Numeric(14,2), default=0)
    icms_st = db.Column(db.Numeric(14,2), default=0)
    ipi = db.Column(db.Numeric(14,2), default=0)
    pis = db.Column(db.Numeric(14,2), default=0)
    cofins = db.Column(db.Numeric(14,2), default=0)
    calc_json = db.Column(db.Text)  # cache do cálculo (JSON)
    calc_version = db.Column(db.String(20))  # versão do algoritmo
    calc_at = db.Column(db.DateTime)  # quando foi calculado
    # JSON agregado com totais por CST/CFOP/NCM etc.
    meta_json = db.Column(db.Text)  # compact JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Relacionamentos
    file = db.relationship("UserFile", backref=db.backref("nfe_summary", uselist=False))

class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
    action = db.Column(db.String(80), nullable=False)   # upload, delete, view, parse, report
    ref = db.Column(db.String(120))                     # e.g., user_file:<id> / nfe:<chave>
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user = db.relationship("User", backref=db.backref("audit_logs", lazy="dynamic"))
