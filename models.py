from __future__ import annotations

import os
import uuid
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from cryptography.fernet import Fernet

# ==========================================================
# CRIPTOGRAFIA (FERNET)
# Em produção, DEFINA FERNET_KEY no ambiente (.env / VPS).
# Se não definir, uma chave temporária será gerada (pode impedir descriptografar depois).
# ==========================================================
_key = os.environ.get("FERNET_KEY")
if _key is None:
    _key = Fernet.generate_key()

cipher = Fernet(_key)

def encrypt(value: str) -> str:
    return cipher.encrypt(value.encode("utf-8")).decode("utf-8")

def decrypt(value: str) -> str:
    return cipher.decrypt(value.encode("utf-8")).decode("utf-8")

# ==========================================================
# SQLALCHEMY
# ==========================================================
db = SQLAlchemy()

# ==========================================================
# MODELOS EXISTENTES
# ==========================================================
class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    protocolo = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))

    # No seu HTML: checkbox "Desejo me identificar" -> True = identificado
    is_public = db.Column(db.Boolean, nullable=False)

    nome = db.Column(db.String(150))
    cpf = db.Column(db.String(14))
    rg = db.Column(db.String(20))
    telefone = db.Column(db.String(20))
    email = db.Column(db.String(150))

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    submissions = db.relationship(
        "Submission",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # Conversas do chat (se você usar usuario_id aqui)
    chat_conversas = db.relationship(
        "ChatConversa",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )


class Submission(db.Model):
    __tablename__ = "submission"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)  # texto, imagem, audio, video
    texto = db.Column(db.Text)

    status = db.Column(db.String(30), nullable=False, default="recebido")
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    files = db.relationship(
        "File",
        backref="submission",
        lazy=True,
        cascade="all, delete-orphan"
    )


class File(db.Model):
    __tablename__ = "file"

    id = db.Column(db.Integer, primary_key=True)

    file_type = db.Column(db.String(20))
    file_path = db.Column(db.String(255))  # ex: static/uploads/uuid.mp4

    original_name = db.Column(db.String(255))
    mime_type = db.Column(db.String(120))
    size_bytes = db.Column(db.Integer)
    sha256 = db.Column(db.String(64))
    uploaded_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    submission_id = db.Column(db.Integer, db.ForeignKey("submission.id"), nullable=False)

# ==========================================================
# NOVOS MODELOS (CHAT CAPIVARA)
# Mesmo banco SQLite + SQLAlchemy
# ==========================================================
class ChatConversa(db.Model):
    __tablename__ = "chat_conversas"

    id = db.Column(db.Integer, primary_key=True)

    # Se você tiver usuário logado, use o id do User.
    # Se for visitante anônimo, pode ficar NULL.
    usuario_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    titulo = db.Column(db.String(120))
    criado_em = db.Column(db.DateTime(timezone=True), server_default=func.now())

    mensagens = db.relationship(
        "ChatMensagem",
        backref="conversa",
        lazy=True,
        cascade="all, delete-orphan"
    )


class ChatMensagem(db.Model):
    __tablename__ = "chat_mensagens"

    id = db.Column(db.Integer, primary_key=True)
    conversa_id = db.Column(db.Integer, db.ForeignKey("chat_conversas.id"), nullable=False)

    # 'usuario' ou 'capivara'
    autor = db.Column(db.String(20), nullable=False)

    conteudo_texto = db.Column(db.Text)
    criado_em = db.Column(db.DateTime(timezone=True), server_default=func.now())

    anexos = db.relationship(
        "ChatAnexo",
        backref="mensagem",
        lazy=True,
        cascade="all, delete-orphan"
    )


class ChatAnexo(db.Model):
    __tablename__ = "chat_anexos"

    id = db.Column(db.Integer, primary_key=True)
    mensagem_id = db.Column(db.Integer, db.ForeignKey("chat_mensagens.id"), nullable=False)

    # 'imagem', 'video', 'audio'
    tipo = db.Column(db.String(10), nullable=False)

    nome_arquivo = db.Column(db.String(255))
    mime_type = db.Column(db.String(120))
    tamanho_bytes = db.Column(db.Integer)

    # Recomendado: salvar caminho/URL pública do arquivo, não o binário no banco
    url_arquivo = db.Column(db.Text)

    criado_em = db.Column(db.DateTime(timezone=True), server_default=func.now())
