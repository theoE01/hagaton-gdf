import os
import uuid
import hashlib
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from models import db, User, Submission, File

upload_bp = Blueprint('upload', __name__)

ALLOWED = {
    'imagem': {'.jpg', '.jpeg', '.png', '.webp'},
    'audio': {'.mp3', '.wav', '.ogg', '.m4a'},
    'video': {'.mp4', '.webm', '.mov'},
    'texto': set(),
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

    files = request.files.getlist('files')

    # Regras mínimas:
    # - texto: pode ir só com texto, sem arquivo
    # - demais: precisa de pelo menos 1 arquivo
    if tipo != 'texto' and (not files or all((f is None) or (f.filename == '') for f in files)):
        flash('Para este tipo, envie ao menos 1 arquivo.', 'error')
        return redirect(url_for('upload.upload_page', protocolo=protocolo))

    submission = Submission(tipo=tipo, texto=texto, user_id=user.id)
    db.session.add(submission)
    db.session.flush()  # garante submission.id

    saved_any = False

    for f in files:
        if not f or not f.filename:
            continue

        original_name = f.filename
        safe_name = secure_filename(original_name)
        ext = _ext(safe_name)

        if tipo != 'texto':
            if ext not in ALLOWED[tipo]:
                flash(f'Arquivo não permitido para {tipo}: {original_name}', 'error')
                db.session.rollback()
                return redirect(url_for('upload.upload_page', protocolo=protocolo))

        internal_name = f"{uuid.uuid4().hex}{ext}" if ext else uuid.uuid4().hex
        dest_dir = current_app.config['UPLOAD_FOLDER']
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, internal_name)

        f.save(dest_path)
        size_bytes = os.path.getsize(dest_path)

        limit = MAX_BYTES.get(tipo, 0)
        if limit and size_bytes > limit:
            try:
                os.remove(dest_path)
            except Exception:
                pass
            flash(f'Arquivo muito grande ({original_name}). Limite para {tipo}: {limit // (1024*1024)}MB.', 'error')
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
        flash('Manifestação registrada com sucesso.', 'success')
        return redirect(url_for('public.protocolo_page', protocolo=protocolo))

    db.session.rollback()
    flash('Nenhum arquivo válido foi enviado.', 'error')
    return redirect(url_for('upload.upload_page', protocolo=protocolo))
