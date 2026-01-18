from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, User

public_bp = Blueprint('public', __name__)

@public_bp.get('/')
def home():
    return render_template('index.html')

@public_bp.post('/create_user')
def create_user():
    # Checkbox: se marcado, usuário se identifica
    is_public = bool(request.form.get('is_public'))

    nome = (request.form.get('nome') or '').strip() or None
    cpf = (request.form.get('cpf') or '').strip() or None
    rg = (request.form.get('rg') or '').strip() or None
    telefone = (request.form.get('telefone') or '').strip() or None
    email = (request.form.get('email') or '').strip() or None

    # Validação mínima: identificado exige ao menos nome OU email
    if is_public and not (nome or email):
        flash('Para envio identificado, informe pelo menos Nome ou E-mail.', 'error')
        return redirect(url_for('public.home'))

    user = User(
        is_public=is_public,
        nome=nome,
        cpf=cpf,
        rg=rg,
        telefone=telefone,
        email=email,
    )
    db.session.add(user)
    db.session.commit()

    return redirect(url_for('public.protocolo_page', protocolo=user.protocolo))

@public_bp.get('/protocolo/<protocolo>')
def protocolo_page(protocolo: str):
    user = User.query.filter_by(protocolo=protocolo).first_or_404()
    return render_template('protocolo.html', protocolo=user.protocolo, is_public=user.is_public)
