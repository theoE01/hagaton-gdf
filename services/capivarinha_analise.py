# services/capivarinha_analise.py
from __future__ import annotations

import os
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app
from groq import Groq

from models import db, User, Submission, File, SubmissionAnalise


# ==========================================================
# CONFIG
# ==========================================================
MAX_INPUT_TEXT = int(os.getenv("CAPI_MAX_INPUT_TEXT", "5500"))  # limite de contexto enviado ao LLM
MAX_TAGS = int(os.getenv("CAPI_MAX_TAGS", "12"))
MAX_RESUMO = int(os.getenv("CAPI_MAX_RESUMO", "220"))
MAX_JSON_CHARS = int(os.getenv("CAPI_MAX_JSON_CHARS", "60000"))

DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


# ==========================================================
# GROQ
# ==========================================================
def _get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não definida no ambiente (.env).")
    # IMPORTANTE: use o padrão do SDK; não passe proxies aqui
    return Groq(api_key=api_key)


# ==========================================================
# JSON helpers (robusto)
# ==========================================================
def _extract_json(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("{") and raw.endswith("}"):
        return raw

    # tenta capturar o maior bloco JSON
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        return m.group(0)

    return raw


def _safe_json_loads(raw: str) -> Dict[str, Any]:
    try:
        return json.loads(_extract_json(raw))
    except Exception:
        return {}


def _safe_load_resultado_json(analise: SubmissionAnalise) -> Dict[str, Any]:
    try:
        if analise and analise.resultado_json:
            return json.loads(analise.resultado_json)
    except Exception:
        pass
    return {}


def _safe_dump_json(data: Dict[str, Any]) -> str:
    s = json.dumps(data, ensure_ascii=False)
    if len(s) > MAX_JSON_CHARS:
        # fallback: mantém só o essencial
        slim = {
            "categoria": data.get("categoria"),
            "prioridade": data.get("prioridade"),
            "tags": data.get("tags"),
            "resumo_curto": data.get("resumo_curto"),
            "graficos_sugeridos": data.get("graficos_sugeridos", [])[:6],
        }
        return json.dumps(slim, ensure_ascii=False)
    return s


# ==========================================================
# Normalizações
# ==========================================================
def _normalize_prioridade(p: Any) -> str:
    p = str(p or "").strip().lower()
    mapa = {
        "baixa": "baixa", "low": "baixa",
        "media": "media", "média": "media", "medium": "media",
        "alta": "alta", "high": "alta",
        "critica": "critica", "crítica": "critica", "critical": "critica",
    }
    return mapa.get(p, "baixa")


def _as_list_str(v: Any, max_items: int = 12) -> List[str]:
    if not isinstance(v, list):
        return []
    out: List[str] = []
    for item in v:
        s = str(item).strip().lower()
        if s:
            out.append(s)
    return out[:max_items]


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        x = int(v)
        return max(lo, min(hi, x))
    except Exception:
        return default


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else (s[: max(0, n - 3)] + "...")


# ==========================================================
# Datasets reais (Chart.js)
# ==========================================================
def _build_chart_suggestions(
    sub: Submission,
    user: User,
    files: List[File],
    base_json: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Gera sugestões de gráficos (datasets reais) baseadas no que temos:
    - quantidade de arquivos por tipo
    - tamanho total por tipo
    - presença de OCR e ASR
    """
    # contagem por tipo
    count_by_type: Dict[str, int] = {}
    size_by_type: Dict[str, int] = {}

    for f in files:
        tp = (f.file_type or "desconhecido").strip().lower()
        count_by_type[tp] = count_by_type.get(tp, 0) + 1
        size_by_type[tp] = size_by_type.get(tp, 0) + int(f.size_bytes or 0)

    labels_tipo = list(count_by_type.keys())
    values_tipo = [count_by_type[k] for k in labels_tipo]

    labels_size = list(size_by_type.keys())
    values_size_mb = [round(size_by_type[k] / (1024 * 1024), 2) for k in labels_size]

    # evidências
    ocr_txt = ""
    try:
        ocr_txt = str(((base_json.get("ocr") or {}).get("resumo")) or "")
    except Exception:
        ocr_txt = ""
    asr_txt = ""
    try:
        asr_txt = str(((base_json.get("midia") or {}).get("resumo")) or "")
    except Exception:
        asr_txt = ""

    evid_labels = ["texto_digitado", "ocr", "asr"]
    evid_values = [
        1 if (sub.texto or "").strip() else 0,
        1 if ocr_txt.strip() else 0,
        1 if asr_txt.strip() else 0,
    ]

    charts: List[Dict[str, Any]] = []

    if labels_tipo:
        charts.append({
            "id": "arquivos_por_tipo",
            "kind": "bar",
            "title": "Arquivos por tipo (esta submission)",
            "labels": labels_tipo,
            "values": values_tipo
        })

    if labels_size:
        charts.append({
            "id": "tamanho_por_tipo",
            "kind": "bar",
            "title": "Tamanho total por tipo (MB) — esta submission",
            "labels": labels_size,
            "values": values_size_mb
        })

    charts.append({
        "id": "evidencias_presentes",
        "kind": "doughnut",
        "title": "Evidências presentes (texto/OCR/ASR)",
        "labels": evid_labels,
        "values": evid_values
    })

    return charts


# ==========================================================
# Montagem de contexto (OCR + ASR + Texto)
# ==========================================================
def _compose_context(sub: Submission, base_json: Dict[str, Any]) -> Dict[str, str]:
    texto_digitado = _truncate(sub.texto or "", 2200)

    ocr_resumo = ""
    try:
        ocr_resumo = str(((base_json.get("ocr") or {}).get("resumo")) or "")
    except Exception:
        ocr_resumo = ""
    ocr_resumo = _truncate(ocr_resumo, 1600)

    asr_resumo = ""
    try:
        asr_resumo = str(((base_json.get("midia") or {}).get("resumo")) or "")
    except Exception:
        asr_resumo = ""
    asr_resumo = _truncate(asr_resumo, 1700)

    # monta um “texto final” que o modelo vai ler
    partes = []
    if texto_digitado.strip():
        partes.append(f"[TEXTO DO CIDADÃO]\n{texto_digitado}")
    if ocr_resumo.strip():
        partes.append(f"[OCR DE IMAGEM]\n{ocr_resumo}")
    if asr_resumo.strip():
        partes.append(f"[TRANSCRIÇÃO (ÁUDIO/VÍDEO)]\n{asr_resumo}")

    combinado = "\n\n".join(partes).strip()
    combinado = _truncate(combinado, MAX_INPUT_TEXT)

    return {
        "texto_digitado": texto_digitado,
        "ocr_resumo": ocr_resumo,
        "asr_resumo": asr_resumo,
        "texto_combinado": combinado,
    }


# ==========================================================
# MAIN
# ==========================================================
def analisar_submission_e_salvar(submission_id: int) -> SubmissionAnalise:
    """
    Gera/atualiza 1 análise por submission.
    Consome automaticamente:
      - texto do cidadão (Submission.texto)
      - OCR (SubmissionAnalise.resultado_json["ocr"])
      - ASR (SubmissionAnalise.resultado_json["midia"])

    Produz:
      - categoria, prioridade, tags, resumo_curto
      - graficos_sugeridos (datasets reais) em resultado_json
    """
    sub = Submission.query.get(submission_id)
    if not sub:
        raise RuntimeError(f"Submission {submission_id} não encontrada.")

    user = User.query.get(sub.user_id)
    if not user:
        raise RuntimeError(f"User {sub.user_id} não encontrado para submission {submission_id}.")

    files = File.query.filter_by(submission_id=sub.id).order_by(File.id.asc()).all()

    # upsert analise (garante que exista para ler OCR/ASR)
    analise = SubmissionAnalise.query.filter_by(submission_id=sub.id).first()
    if not analise:
        analise = SubmissionAnalise(
            submission_id=sub.id,
            user_id=user.id,
            protocolo=user.protocolo,
            categoria="não_classificado",
            prioridade="baixa",
            tags_json="[]",
            resumo_curto="",
            resultado_json=None,
            modelo=None
        )
        db.session.add(analise)
        db.session.commit()

    # lê o JSON atual (onde OCR/ASR provavelmente já foram gravados)
    base_json = _safe_load_resultado_json(analise)

    # contexto unificado
    ctx = _compose_context(sub, base_json)

    # sugestões de gráficos (datasets reais)
    charts = _build_chart_suggestions(sub, user, files, base_json)

    # ----------------------------
    # Prompt “forte” JSON-only
    # ----------------------------
    categorias = [
        "pavimentacao", "iluminacao_publica", "limpeza_urbana", "transporte",
        "seguranca", "saude", "educacao", "meio_ambiente", "ruido",
        "denuncia", "sugestao", "reclamacao", "elogio", "informacao", "outros"
    ]

    system = (
        "Você é a Capivarinha GDF, analista de triagem administrativa. "
        "Classifique a manifestação e produza um resumo curto. "
        "Use SOMENTE o texto fornecido (texto digitado + OCR + transcrição). "
        "Responda SOMENTE em JSON válido (um único objeto), sem markdown e sem texto fora do JSON."
    )

    schema = {
        "categoria": f"string (1 dentre {categorias})",
        "prioridade": "string (baixa|media|alta|critica)",
        "tags": ["string (3 a 10 tags curtas pt-BR)"],
        "resumo_curto": f"string (max {MAX_RESUMO} chars, objetivo, sem emojis)",
        "sentimento": "string (negativo|neutro|positivo)",
        "confianca": "int (0-100)",
        "pontos_chave": ["string (até 6 itens)"],
        "necessita_mais_dados": "bool",
        "dados_faltantes": ["string (se necessitar)"],
        "observacoes": "string (opcional)"
    }

    # dados mínimos (sem PII)
    payload = {
        "protocolo": user.protocolo,
        "submission_id": sub.id,
        "tipo": (sub.tipo or "").lower(),
        "contexto_texto": ctx["texto_combinado"],
        "arquivos": [{
            "id": f.id,
            "tipo": (f.file_type or ""),
            "nome": (f.original_name or ""),
            "mime": (f.mime_type or ""),
            "tamanho_bytes": int(f.size_bytes or 0),
        } for f in files[:20]]
    }

    client = _get_client()
    model = DEFAULT_MODEL

    raw = ""
    data: Dict[str, Any] = {}
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": (
                    "Retorne um JSON seguindo este FORMATO:\n"
                    f"{json.dumps(schema, ensure_ascii=False)}\n\n"
                    "Agora analise estes DADOS:\n"
                    f"{json.dumps(payload, ensure_ascii=False)}\n\n"
                    "REGRAS:\n"
                    "- Responda apenas JSON válido.\n"
                    "- Não invente dados fora do contexto_texto.\n"
                    "- Se o contexto estiver vazio, marque necessita_mais_dados=true.\n"
                )}
            ],
            temperature=0.2,
            max_tokens=650
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = _safe_json_loads(raw)

        if not data:
            raise ValueError("Resposta não retornou JSON válido.")
    except Exception as e:
        current_app.logger.exception("[capivarinha_analise] Falha na análise Groq")
        data = {
            "categoria": "outros",
            "prioridade": "baixa",
            "tags": ["falha_ia"],
            "resumo_curto": "Não foi possível classificar automaticamente agora.",
            "sentimento": "neutro",
            "confianca": 0,
            "pontos_chave": [],
            "necessita_mais_dados": True if not ctx["texto_combinado"].strip() else False,
            "dados_faltantes": ["texto", "imagem/áudio/vídeo com conteúdo legível"] if not ctx["texto_combinado"].strip() else [],
            "observacoes": str(e)[:240]
        }
        raw = json.dumps(data, ensure_ascii=False)

    # ----------------------------
    # Normalização final p/ colunas
    # ----------------------------
    categoria = str(data.get("categoria") or "outros").strip().lower()[:60]
    prioridade = _normalize_prioridade(data.get("prioridade"))[:20]
    tags = _as_list_str(data.get("tags"), max_items=MAX_TAGS)
    resumo_curto = _truncate(str(data.get("resumo_curto") or ""), MAX_RESUMO)
    sentimento = str(data.get("sentimento") or "neutro").strip().lower()
    confianca = _clamp_int(data.get("confianca"), 0, 100, 50)

    # reforça consistência
    data["categoria"] = categoria
    data["prioridade"] = prioridade
    data["tags"] = tags
    data["resumo_curto"] = resumo_curto
    data["sentimento"] = sentimento if sentimento in ("negativo", "neutro", "positivo") else "neutro"
    data["confianca"] = confianca

    # injeta contexto consumido (para auditoria) + charts reais
    base_json["capivarinha"] = {
        "entrada": {
            "texto_digitado": ctx["texto_digitado"],
            "ocr_resumo": ctx["ocr_resumo"],
            "asr_resumo": ctx["asr_resumo"],
        },
        "saida": data,
        "raw_model_output": raw[:12000],  # guarda um pedaço
    }
    base_json["graficos_sugeridos"] = charts

    # escreve nas colunas principais
    analise.categoria = categoria
    analise.prioridade = prioridade
    analise.tags_json = json.dumps(tags, ensure_ascii=False)
    analise.resumo_curto = resumo_curto
    analise.resultado_json = _safe_dump_json(base_json)
    analise.modelo = model

    db.session.commit()

    try:
        current_app.logger.info(
            f"[capivarinha_analise] OK submission_id={sub.id} cat={categoria} prio={prioridade} conf={confianca} charts={len(charts)}"
        )
    except Exception:
        pass

    return analise
