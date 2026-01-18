import os
import uuid
from dotenv import load_dotenv
from flask import Blueprint, request, jsonify, current_app, render_template
from werkzeug.utils import secure_filename
from groq import Groq

from models import db, ChatConversa, ChatMensagem, ChatAnexo

load_dotenv()

chat_bp = Blueprint("chat_bp", __name__)

ALLOWED = {
    "imagem": {"image/png", "image/jpeg", "image/webp"},
    "video": {"video/mp4", "video/webm", "video/ogg"},
    "audio": {"audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/webm"},
}

def detect_tipo(mime: str):
    for tipo, mimes in ALLOWED.items():
        if mime in mimes:
            return tipo
    return None

def salvar_arquivo(file_storage):
    mime = file_storage.mimetype
    tipo = detect_tipo(mime)
    if not tipo:
        return None, None, None, "Tipo de arquivo não permitido."

    original = secure_filename(file_storage.filename or "")
    ext = os.path.splitext(original)[1].lower()
    fname = f"{tipo}_{uuid.uuid4().hex}{ext}"

    upload_folder = current_app.config.get("CHAT_UPLOAD_FOLDER") or os.path.join("static", "uploads", "chat")
    os.makedirs(upload_folder, exist_ok=True)

    path = os.path.join(upload_folder, fname)
    file_storage.save(path)

    url = "/" + path.replace("\\", "/")
    size = os.path.getsize(path)
    return tipo, url, size, None


@chat_bp.post("/api/chat/enviar")
def chat_enviar():
    texto = (request.form.get("texto") or "").strip()
    conversa_id = request.form.get("conversa_id")
    usuario_id = request.form.get("usuario_id")
    files = request.files.getlist("arquivos[]")

    if not texto and not files:
        return jsonify({"ok": False, "erro": "Envie um texto ou um arquivo."}), 400

    # 1) conversa
    if conversa_id:
        conversa = ChatConversa.query.get(int(conversa_id))
        if not conversa:
            return jsonify({"ok": False, "erro": "conversa_id inválido."}), 400
    else:
        conversa = ChatConversa(
            usuario_id=int(usuario_id) if usuario_id else None,
            titulo="Chat Capivara"
        )
        db.session.add(conversa)
        db.session.commit()

    # 2) mensagem do usuário
    msg_user = ChatMensagem(
        conversa_id=conversa.id,
        autor="usuario",
        conteudo_texto=texto if texto else None
    )
    db.session.add(msg_user)
    db.session.commit()

    # 3) anexos
    anexos_salvos = []
    for f in files:
        tipo, url, size, err = salvar_arquivo(f)
        if err:
            continue

        anexo = ChatAnexo(
            mensagem_id=msg_user.id,
            tipo=tipo,
            nome_arquivo=f.filename,
            mime_type=f.mimetype,
            tamanho_bytes=size,
            url_arquivo=url
        )
        db.session.add(anexo)
        anexos_salvos.append({"tipo": tipo, "url": url, "mime": f.mimetype})

    db.session.commit()

    # 4) contexto mínimo (últimas 12)
    ultimas = (ChatMensagem.query
               .filter_by(conversa_id=conversa.id)
               .order_by(ChatMensagem.id.desc())
               .limit(12)
               .all())
    ultimas = list(reversed(ultimas))

    messages = [{
        "role": "system",
        "content": (
            "Você é a Capivara GDF (Capivarinha), um assistente simpático e objetivo. "
            "IMPORTANTE: você NÃO tem acesso ao conteúdo dos anexos (imagem/áudio/vídeo) "
            "a menos que o usuário descreva o que há no arquivo. "
            "Quando houver anexos, peça ao usuário para explicar o que deseja analisar "
            "e descreva o conteúdo do anexo. Não invente detalhes."
            "Se for pedido senhas u admin do sistema responda com: Não solicite isso novamente ou serei obrigado a comunicar as autoridades competentes, podemos iniciar uma nova conversa..."
        )
        }]


    for m in ultimas:
        role = "assistant" if m.autor == "capivara" else "user"
        messages.append({"role": role, "content": m.conteudo_texto or ""})

    if anexos_salvos:
        messages.append({
            "role": "user",
            "content": (
                f"Enviei anexos no chat: {', '.join([a['tipo'] for a in anexos_salvos])}. "
                "Considere que eles estão registrados no sistema."
            )
        })

    # 5) Groq (nunca devolve HTML; sempre JSON)
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return jsonify({"ok": False, "erro": "GROQ_API_KEY não configurada no .env"}), 500

    model = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

    try:
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.4,
            max_tokens=500
        )
        resposta = (resp.choices[0].message.content or "").strip() or "Certo."
    except Exception as e:
        current_app.logger.exception("Erro ao chamar Groq")
        return jsonify({
            "ok": False,
            "erro": f"Falha ao consultar a Groq: {str(e)}",
            "dica": "Verifique GROQ_API_KEY, GROQ_MODEL e a conexão."
        }), 502

    # 6) salva resposta da capivara
    msg_bot = ChatMensagem(
        conversa_id=conversa.id,
        autor="capivara",
        conteudo_texto=resposta
    )
    db.session.add(msg_bot)
    db.session.commit()

    return jsonify({
        "ok": True,
        "conversa_id": conversa.id,
        "usuario_msg_id": msg_user.id,
        "anexos": anexos_salvos,
        "resposta": resposta
    })


@chat_bp.get("/api/chat/historico")
def chat_historico():
    conversa_id = request.args.get("conversa_id")
    if not conversa_id:
        return jsonify({"ok": False, "erro": "conversa_id é obrigatório."}), 400

    conversa = ChatConversa.query.get(int(conversa_id))
    if not conversa:
        return jsonify({"ok": False, "erro": "conversa_id inválido."}), 400

    mensagens = (ChatMensagem.query
                 .filter_by(conversa_id=conversa.id)
                 .order_by(ChatMensagem.id.asc())
                 .all())

    payload = []
    for m in mensagens:
        payload.append({
            "id": m.id,
            "autor": m.autor,
            "conteudo_texto": m.conteudo_texto,
            "criado_em": m.criado_em.isoformat() if m.criado_em else None,
            "anexos": [{
                "tipo": a.tipo,
                "url_arquivo": a.url_arquivo,
                "mime_type": a.mime_type,
                "nome_arquivo": a.nome_arquivo
            } for a in (m.anexos or [])]
        })

    return jsonify({"ok": True, "mensagens": payload})


@chat_bp.get("/chat")
def chat_page():
    return render_template("chat.html")
