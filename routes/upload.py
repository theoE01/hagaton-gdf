import os
import uuid
import hashlib
import threading

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename

from models import db, User, Submission, File


upload_bp = Blueprint('upload', __name__)

ALLOWED = {
    'imagem': {'.jpg', '.jpeg', '.png', '.webp'},
    'audio': {'.mp3', '.wav', '.ogg', '.m4a'},
    'video': {'.mp4', '.webm', '.mov'},
    'texto': set(),  # texto pode vir sem arquivo
}

MAX_BYTES = {
    'imagem': 10 * 1024 * 1024,   # 10MB
    'audio': 25 * 1024 * 1024,    # 25MB
    'video': 200 * 1024 * 1024,   # 200MB
    'texto': 0,
}


def _sha256_of_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _ext(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


@upload_bp.get('/upload/<protocolo>')
def upload_page(protocolo: str):
    user = User.query.filter_by(protocolo=protocolo).first_or_404()
    return render_template('upload.html', protocolo=user.protocolo)


def _disparar_pipeline_bg(submission_id: int) -> None:
    """
    Dispara OCR/ASR + cache LLM em background, dentro de app_context.
    Não pode quebrar o fluxo do cidadão.
    """
    try:
        app_obj = current_app._get_current_object()

        def _worker(sub_id: int):
            with app_obj.app_context():
                # 1) OCR (imagens)
                try:
                    from services.imagem_analise import analisar_imagem_e_salvar
                    analisar_imagem_e_salvar(sub_id)
                except Exception:
                    app_obj.logger.exception(f"[BG] Falha OCR (submission_id={sub_id})")

                # 2) ASR/transcrição (áudio/vídeo)
                try:
                    from services.midia_analise import analisar_midia_e_salvar
                    analisar_midia_e_salvar(sub_id)
                except Exception:
                    app_obj.logger.exception(f"[BG] Falha ASR (submission_id={sub_id})")

                # 3) Triagem/LLM (Groq) — ideal: usar texto+OCR+ASR no serviço
                try:
                    from services.capivarinha_analise import analisar_submission_e_salvar
                    analisar_submission_e_salvar(sub_id)
                except Exception:
                    app_obj.logger.exception(f"[BG] Falha LLM (submission_id={sub_id})")

        threading.Thread(target=_worker, args=(submission_id,), daemon=True).start()

    except Exception:
        # não deixa o request cair por causa de background
        current_app.logger.exception("Falha ao disparar pipeline de análises (OCR/ASR/LLM).")


@upload_bp.post('/upload')
def upload_submit():
    protocolo = (request.form.get('protocolo') or '').strip()
    tipo = (request.form.get('tipo') or '').strip().lower()
    texto = (request.form.get('texto') or '').strip() or None

    user = User.query.filter_by(protocolo=protocolo).first()
    if not user:
        flash('Protocolo não encontrado. Verifique e tente novamente.', 'error')
        return redirect(url_for('public.home'))

    if tipo not in ALLOWED:
        flash('Tipo de manifestação inválido.', 'error')
        return redirect(url_for('upload.upload_page', protocolo=protocolo))

    files = request.files.getlist('files') or []

    # Regra mínima:
    # - texto: pode ir só com texto, sem arquivo
    # - demais: precisa de pelo menos 1 arquivo válido
    if tipo != 'texto':
        tem_arquivo = any((f is not None) and (f.filename or '').strip() for f in files)
        if not tem_arquivo:
            flash('Para este tipo, envie ao menos 1 arquivo.', 'error')
            return redirect(url_for('upload.upload_page', protocolo=protocolo))

    submission = Submission(tipo=tipo, texto=texto, user_id=user.id)
    db.session.add(submission)
    db.session.flush()  # garante submission.id sem commit

    saved_any = False

    for f in files:
        if (f is None) or not (f.filename or '').strip():
            continue

        original_name = f.filename
        safe_name = secure_filename(original_name)
        ext = _ext(safe_name)

        # valida extensão quando não é "texto"
        if tipo != 'texto':
            if ext not in ALLOWED[tipo]:
                flash(f'Arquivo não permitido para {tipo}: {original_name}', 'error')
                db.session.rollback()
                return redirect(url_for('upload.upload_page', protocolo=protocolo))

        internal_name = f"{uuid.uuid4().hex}{ext}" if ext else uuid.uuid4().hex
        dest_dir = current_app.config['UPLOAD_FOLDER']
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, internal_name)

        try:
            f.save(dest_path)
        except Exception:
            current_app.logger.exception("Falha ao salvar arquivo no disco.")
            flash(f'Falha ao salvar o arquivo: {original_name}', 'error')
            db.session.rollback()
            return redirect(url_for('upload.upload_page', protocolo=protocolo))

        size_bytes = os.path.getsize(dest_path)

        limit = MAX_BYTES.get(tipo, 0)
        if limit and size_bytes > limit:
            try:
                os.remove(dest_path)
            except Exception:
                pass
            flash(
                f'Arquivo muito grande ({original_name}). Limite para {tipo}: {limit // (1024 * 1024)}MB.',
                'error'
            )
            db.session.rollback()
            return redirect(url_for('upload.upload_page', protocolo=protocolo))

        sha256 = _sha256_of_file(dest_path)

        db_file = File(
            file_type=tipo,
            file_path=f"static/uploads/{internal_name}",
            original_name=original_name,
            mime_type=f.mimetype,
            size_bytes=size_bytes,
            sha256=sha256,
            submission_id=submission.id,
        )
        db.session.add(db_file)
        saved_any = True

    # texto pode ser só texto
    if tipo == 'texto' or saved_any:
        db.session.commit()

        # 🔥 dispara pipeline completo em background (OCR/ASR/LLM)
        _disparar_pipeline_bg(submission.id)

        flash('Manifestação registrada com sucesso.', 'success')
        return redirect(url_for('public.protocolo_page', protocolo=protocolo))

    db.session.rollback()
    flash('Nenhum arquivo válido foi enviado.', 'error')
    return redirect(url_for('upload.upload_page', protocolo=protocolo))
