import os
import datetime
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    current_app, abort, jsonify
)

from flask import send_file

from models import User, Submission, File

from groq import Groq


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

@admin_bp.get('/analises')
@login_required
def capivarinha_analises():
    # Página exclusiva do admin
    admin_user = session.get('admin_user', '-')
    _audit("VIEW_CAPIVARINHA_ANALISES", f"admin_user={admin_user}")
    return render_template('admin_capivarinha.html')


@admin_bp.post('/api/capivarinha/perguntar')
@login_required
def capivarinha_perguntar():
    """
    Recebe: {"pergunta": "..."}

    Retorna:
      {
        "ok": True,
        "resposta_texto": "...",
        "grafico": { kind,title,labels,values } OU { kind,title,labels,datasets },
        "meta": {...}
      }
    """
    data = request.get_json(silent=True) or {}
    pergunta = (data.get("pergunta") or "").strip()
    q = pergunta.lower()

    if not pergunta:
        return jsonify({"ok": False, "erro": "Pergunta vazia."}), 400

    # ----------------------------
    # 1) Coleta/Agregação (LGPD-safe)
    # ----------------------------
    # Pegue uma janela "recente" para estatística (e evitar tokens)
    # OBS: se quiser, troque para um filtro por data (last 30 days).
    users = User.query.order_by(User.id.desc()).limit(120).all()

    total_subs = 0
    status_count = {}
    tipo_count = {}
    modo_count = {"anonimo": 0, "identificado": 0}
    subs_por_dia = {}  # YYYY-MM-DD -> count

    # Amostra textual bem pequena (para o LLM não explodir tokens)
    # Mantemos no máximo 40 itens e truncamos texto.
    amostra_textual = []

    for u in users:
        modo = "identificado" if bool(getattr(u, "is_public", False)) else "anonimo"
        modo_count[modo] = modo_count.get(modo, 0) + 1

        subs = Submission.query.filter_by(user_id=u.id).order_by(Submission.id.desc()).limit(20).all()
        total_subs += len(subs)

        for s in subs:
            st = (s.status or "sem_status").strip().lower()
            status_count[st] = status_count.get(st, 0) + 1

            tp = (s.tipo or "sem_tipo").strip().lower()
            tipo_count[tp] = tipo_count.get(tp, 0) + 1

            # série temporal por dia
            dt = getattr(s, "created_at", None)
            if dt:
                day = dt.date().isoformat()
                subs_por_dia[day] = subs_por_dia.get(day, 0) + 1

        # amostra textual (não manda CPF/nome/email etc.)
        if len(amostra_textual) < 40 and subs:
            s0 = subs[0]
            amostra_textual.append({
                "protocolo": u.protocolo,
                "modo": modo,
                "tipo": (s0.tipo or ""),
                "status": (s0.status or ""),
                "texto": (s0.texto or "")[:260]
            })

    # Ordena série temporal
    dias_ordenados = sorted(subs_por_dia.keys())
    valores_dias = [subs_por_dia[d] for d in dias_ordenados]

    # Top N utilitário
    def top_n(d, n=10):
        items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)
        return items[:n]

    top_status = top_n(status_count, 10)
    top_tipos = top_n(tipo_count, 10)

    # ----------------------------
    # 2) Decide se precisa de gráfico e qual
    # ----------------------------
    wants_chart = any(k in q for k in ["gráfico", "grafico", "chart", "barra", "pizza", "linha", "tendência", "tendencia", "top", "rank"])

    # escolha do tipo do chart
    # - se pedir "pizza/rosca": pie/doughnut
    # - se pedir "linha/tendência": line
    # - se pedir "horizontal": bar_horizontal
    chart_kind = "bar"
    if any(k in q for k in ["pizza", "pie"]):
        chart_kind = "pie"
    elif any(k in q for k in ["rosca", "doughnut", "donut"]):
        chart_kind = "doughnut"
    elif any(k in q for k in ["linha", "tendência", "tendencia", "evolução", "evolucao"]):
        chart_kind = "line"
    elif "horizontal" in q:
        chart_kind = "bar_horizontal"

    # alvo do chart
    target = "status"
    if "tipo" in q:
        target = "tipo"
    elif any(k in q for k in ["modo", "anonimo", "anônimo", "identificado"]):
        target = "modo"
    elif any(k in q for k in ["tendência", "tendencia", "evolução", "evolucao", "semana", "dia", "dias"]):
        target = "tendencia"

    grafico = None
    if wants_chart:
        if target == "tipo":
            labels = [k for k, _ in top_tipos]
            values = [v for _, v in top_tipos]
            grafico = {
                "title": "Top tipos de submissions (amostra)",
                "labels": labels,
                "values": values,
                "kind": chart_kind if chart_kind != "line" else "bar"  # line não faz sentido p/ categorias
            }

        elif target == "modo":
            labels = ["anonimo", "identificado"]
            values = [modo_count.get("anonimo", 0), modo_count.get("identificado", 0)]
            grafico = {
                "title": "Protocolos por modo",
                "labels": labels,
                "values": values,
                "kind": "doughnut" if chart_kind in ["pie", "doughnut"] else "bar"
            }

        elif target == "tendencia":
            # line com 1 dataset
            grafico = {
                "title": "Tendência de submissions por dia (amostra)",
                "labels": dias_ordenados[-30:],  # últimos 30 dias disponíveis
                "datasets": [{
                    "label": "Submissions",
                    "data": valores_dias[-30:]
                }],
                "kind": "line"
            }

        else:
            # status
            labels = [k for k, _ in top_status]
            values = [v for _, v in top_status]
            grafico = {
                "title": "Top status de submissions (amostra)",
                "labels": labels,
                "values": values,
                "kind": chart_kind if chart_kind != "line" else "bar"
            }

    # ----------------------------
    # 3) Chamada Groq (texto consultivo)
    # ----------------------------
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL")

    if not api_key:
        return jsonify({"ok": False, "erro": "GROQ_API_KEY não configurada no .env."}), 500
    if not model:
        return jsonify({"ok": False, "erro": "GROQ_MODEL não configurado no .env."}), 500

    admin_user = session.get('admin_user', '-')
    _audit("CAPIVARINHA_ASK", f"admin_user={admin_user} pergunta={pergunta[:160]}")

    # Dados agregados (o que o LLM deve usar)
    pacote_gerencial = {
        "janela_users": len(users),
        "total_submissions": total_subs,
        "status_count_top10": top_status,
        "tipo_count_top10": top_tipos,
        "modo_count": modo_count,
        "tendencia_last_days": list(zip(dias_ordenados[-14:], valores_dias[-14:])),
        "amostra_textual": amostra_textual
    }

    system = (
        "Você é a Capivarinha GDF, assistente de análises do ADMIN do sistema Participa DF. "
        "Use SOMENTE os dados agregados fornecidos. "
        "Não invente números nem detalhes. "
        "Se a pergunta pedir algo fora do pacote, explique o que falta e sugira como coletar."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"DADOS (agregados):\n{jsonify(pacote_gerencial).get_data(as_text=True)}"},
        {"role": "user", "content": f"PERGUNTA DO ADMIN:\n{pergunta}\n\n"
                                    "Responda em pt-BR, objetivo, e traga insights acionáveis."}
    ]

    try:
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.25,
            max_tokens=850
        )
        resposta_texto = (resp.choices[0].message.content or "").strip() or "Certo."
    except Exception as e:
        _audit("CAPIVARINHA_FAIL", f"admin_user={admin_user} err={str(e)[:220]}")
        return jsonify({"ok": False, "erro": f"Falha ao consultar a Groq: {str(e)}"}), 502

    # ----------------------------
    # 4) Retorno
    # ----------------------------
    payload = {
        "ok": True,
        "resposta_texto": resposta_texto,
        "meta": {
            "protocolos_consultados": len(users),
            "submissions_consultadas": total_subs,
            "grafico_gerado": bool(grafico),
            "alvo": target
        }
    }
    if grafico:
        payload["grafico"] = grafico

    _audit("CAPIVARINHA_OK", f"admin_user={admin_user} chart={bool(grafico)} alvo={target}")
    return jsonify(payload)
