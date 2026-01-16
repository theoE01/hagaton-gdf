import os
import datetime
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    current_app, abort
)
from flask import send_file

from models import User, Submission, File

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# MVP: admin fixo via env. (produção: hash + tabela de admins)
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS', 'admin123')


def _audit(action: str, details: str = "") -> None:
    """Auditoria simples em arquivo (MVP)."""
    try:
        log_path = os.path.join(current_app.root_path, 'admin_audit.log')
        ip = request.headers.get('X-Forwarded-For', request.remote_addr) or "-"
        ua = request.headers.get('User-Agent', '-') or "-"
        line = f"[{datetime.datetime.now().isoformat()}] {action} ip={ip} ua={ua} {details}\n"
        with open(log_path, 'a', encoding='utf-8') as fp:
            fp.write(line)
    except Exception:
        # Em MVP, auditoria não pode derrubar o sistema
        pass


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin_logged'):
            return redirect(url_for('admin.login'))
        return fn(*args, **kwargs)
    return wrapper


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Hardening opcional de sessão (não quebra)
    current_app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
    current_app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')

    if request.method == 'POST':
        user = (request.form.get('user') or '').strip()
        password = (request.form.get('password') or '').strip()

        if user == ADMIN_USER and password == ADMIN_PASS:
            session['admin_logged'] = True
            session['admin_user'] = user
            _audit("LOGIN_OK", f"admin_user={user}")
            return redirect(url_for('admin.dashboard'))

        _audit("LOGIN_FAIL", f"admin_user={user}")
        return render_template('admin_login.html', error='Credenciais inválidas.')

    return render_template('admin_login.html')


@admin_bp.get('/logout')
def logout():
    admin_user = session.get('admin_user', '-')
    session.pop('admin_logged', None)
    session.pop('admin_user', None)
    _audit("LOGOUT", f"admin_user={admin_user}")
    return redirect(url_for('admin.login'))


@admin_bp.get('/')
@login_required
def dashboard():
    users = User.query.order_by(User.id.desc()).limit(50).all()
    _audit("VIEW_DASHBOARD", f"count={len(users)}")
    return render_template('admin_dashboard.html', users=users)


@admin_bp.get('/protocolo/<protocolo>')
@login_required
def view_protocolo(protocolo: str):
    user = User.query.filter_by(protocolo=protocolo).first_or_404()
    submissions = Submission.query.filter_by(user_id=user.id).order_by(Submission.id.desc()).all()
    _audit("VIEW_PROTOCOL", f"protocolo={protocolo} submissions={len(submissions)}")
    return render_template('admin_protocolo.html', user=user, submissions=submissions)


@admin_bp.get('/download/<int:file_id>')
@login_required
def download_file(file_id: int):
    f = File.query.get_or_404(file_id)

    # file_path salva algo como: "static/uploads/uuid.ext"
    safe_rel = (f.file_path or "").replace('\\', '/').lstrip('/')
    if not safe_rel:
        abort(404)

    abs_path = os.path.abspath(os.path.join(current_app.root_path, safe_rel))

    # Proteção contra path traversal: arquivo deve estar dentro de static/uploads
    uploads_dir = os.path.abspath(os.path.join(current_app.root_path, 'static', 'uploads'))
    if not abs_path.startswith(uploads_dir + os.sep) and abs_path != uploads_dir:
        abort(403)

    if not os.path.exists(abs_path):
        abort(404)

    admin_user = session.get('admin_user', '-')
    _audit(
        "DOWNLOAD_FILE",
        f"admin_user={admin_user} file_id={f.id} original_name={f.original_name} path={f.file_path} sha256={f.sha256}"
    )

    download_name = f.original_name or os.path.basename(abs_path)
    return send_file(abs_path, as_attachment=True, download_name=download_name)
