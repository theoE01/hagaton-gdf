# services/midia_analise.py
from __future__ import annotations

import os
import json
import subprocess
import tempfile
from typing import Optional, Dict, Any, Tuple, List

from flask import current_app
from faster_whisper import WhisperModel

from models import db, Submission, File, SubmissionAnalise


# ==========================================================
# CONFIG
# ==========================================================
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")  # tiny|base|small|medium|large-v3
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")            # cpu|cuda
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")         # int8|float16|float32
WHISPER_LANG = os.getenv("WHISPER_LANG", "pt")                 # hint
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")

# limites de segurança
MAX_TRANSCRIPT_CHARS = int(os.getenv("MIDIA_MAX_TRANSCRIPT_CHARS", "20000"))
MAX_SEGMENTS = int(os.getenv("MIDIA_MAX_SEGMENTS", "1200"))
MAX_FILES_TO_PROCESS = int(os.getenv("MIDIA_MAX_FILES", "4"))   # evita travar CPU
VAD_MIN_SILENCE_MS = int(os.getenv("VAD_MIN_SILENCE_MS", "500"))

# MIMES comuns
AUDIO_MIMES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/ogg", "audio/mp4", "audio/x-m4a", "audio/aac"
}
VIDEO_MIMES = {
    "video/mp4", "video/webm", "video/quicktime", "video/x-matroska"
}

# Extensões (fallback quando mime é fraco/ausente)
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv"}


# ==========================================================
# WHISPER CACHE (carrega 1x por processo)
# ==========================================================
_WHISPER_MODEL: WhisperModel | None = None


def _get_whisper_model() -> WhisperModel:
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        _WHISPER_MODEL = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE
        )
        try:
            current_app.logger.info(
                f"[midia_analise] Whisper carregado: size={WHISPER_MODEL_SIZE} device={WHISPER_DEVICE} compute={WHISPER_COMPUTE}"
            )
        except Exception:
            pass
    return _WHISPER_MODEL


# ==========================================================
# HELPERS
# ==========================================================
def _abs_path_from_file_path(rel_path: str) -> str:
    safe_rel = (rel_path or "").replace("\\", "/").lstrip("/")
    return os.path.abspath(os.path.join(current_app.root_path, safe_rel))


def _is_audio(file: File) -> bool:
    mt = (file.mime_type or "").lower().strip()
    if mt in AUDIO_MIMES:
        return True
    ext = os.path.splitext((file.file_path or "").lower())[1]
    return ext in AUDIO_EXTS or (file.file_type or "").lower() == "audio"


def _is_video(file: File) -> bool:
    mt = (file.mime_type or "").lower().strip()
    if mt in VIDEO_MIMES:
        return True
    ext = os.path.splitext((file.file_path or "").lower())[1]
    return ext in VIDEO_EXTS or (file.file_type or "").lower() == "video"


def _ffmpeg_extract_audio(src_video: str, dst_wav: str) -> None:
    """
    Extrai áudio de um vídeo e salva WAV 16kHz mono.
    Requer ffmpeg no PATH ou definido em FFMPEG_BIN.
    """
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", src_video,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        dst_wav
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {p.stderr[:400]}")


def _transcribe_audio(audio_path: str) -> Tuple[str, Dict[str, Any]]:
    """
    Retorna (texto, meta) com segments.
    """
    model = _get_whisper_model()

    segments, info = model.transcribe(
        audio_path,
        language=WHISPER_LANG,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=VAD_MIN_SILENCE_MS)
    )

    parts: List[str] = []
    segs: List[Dict[str, Any]] = []

    for i, s in enumerate(segments):
        if i >= MAX_SEGMENTS:
            break
        t = (s.text or "").strip()
        if t:
            parts.append(t)
        segs.append({
            "start": float(s.start),
            "end": float(s.end),
            "text": t
        })

    text = " ".join(parts).strip()
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = text[:MAX_TRANSCRIPT_CHARS] + "..."

    meta = {
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
        "segments": segs
    }

    return text, meta


def _safe_json_loads(s: str) -> Dict[str, Any]:
    try:
        if not s:
            return {}
        return json.loads(s)
    except Exception:
        return {"raw": s}


def _ensure_analise(sub: Submission) -> SubmissionAnalise:
    analise = SubmissionAnalise.query.filter_by(submission_id=sub.id).first()
    if analise:
        return analise

    protocolo = ""
    try:
        protocolo = sub.user.protocolo if sub.user else ""
    except Exception:
        protocolo = ""

    analise = SubmissionAnalise(
        submission_id=sub.id,
        user_id=sub.user_id,
        protocolo=protocolo,
        categoria="não_classificado",
        prioridade="baixa",
        tags_json="[]",
        resumo_curto="",
        resultado_json=None,
        modelo=None
    )
    db.session.add(analise)
    db.session.commit()
    return analise


# ==========================================================
# MAIN
# ==========================================================
def analisar_midia_e_salvar(submission_id: int) -> Optional[SubmissionAnalise]:
    """
    Enriquecimento multimídia:
      - Transcreve todos os áudios/vídeos da submission (até MAX_FILES_TO_PROCESS)
      - Para vídeo, extrai áudio (wav 16k mono) via ffmpeg
      - Salva em SubmissionAnalise.resultado_json em base["midia"]
    """
    sub = Submission.query.get(submission_id)
    if not sub:
        return None

    analise = _ensure_analise(sub)

    files = File.query.filter_by(submission_id=sub.id).order_by(File.id.asc()).all()
    if not files:
        return analise

    # filtra midia
    midias = [f for f in files if _is_audio(f) or _is_video(f)]
    if not midias:
        return analise

    midias = midias[:MAX_FILES_TO_PROCESS]

    base = _safe_json_loads(analise.resultado_json or "")
    base.setdefault("midia", {})
    base["midia"].setdefault("transcricoes", [])
    base["midia"].setdefault("erros", [])

    transcricoes: List[Dict[str, Any]] = []
    erros: List[Dict[str, Any]] = []

    for f in midias:
        src_abs = _abs_path_from_file_path(f.file_path)
        if not os.path.exists(src_abs):
            erros.append({
                "file_id": f.id,
                "original_name": f.original_name,
                "erro": "arquivo_nao_encontrado"
            })
            continue

        try:
            is_video = _is_video(f)

            if is_video:
                with tempfile.TemporaryDirectory() as tmp:
                    wav_path = os.path.join(tmp, "audio.wav")
                    _ffmpeg_extract_audio(src_abs, wav_path)
                    text, meta = _transcribe_audio(wav_path)
            else:
                text, meta = _transcribe_audio(src_abs)

            transcricoes.append({
                "file_id": f.id,
                "file_type": (f.file_type or ""),
                "mime_type": (f.mime_type or ""),
                "original_name": (f.original_name or ""),
                "file_path": (f.file_path or ""),
                "transcricao_texto": text,
                "transcricao_meta": meta
            })

            try:
                current_app.logger.info(
                    f"[midia_analise] OK submission_id={sub.id} file_id={f.id} chars={len(text)}"
                )
            except Exception:
                pass

        except Exception as e:
            erros.append({
                "file_id": f.id,
                "original_name": (f.original_name or ""),
                "erro": str(e)[:600]
            })
            try:
                current_app.logger.exception(f"[midia_analise] falha file_id={f.id}")
            except Exception:
                pass

    # agrega resumo rápido (para a LLM consumir)
    resumo_txt = []
    for t in transcricoes:
        tx = (t.get("transcricao_texto") or "").strip()
        if tx:
            resumo_txt.append(f"- {t.get('original_name','arquivo')}: {tx[:900]}")

    resumo_agregado = "\n".join(resumo_txt).strip()
    if len(resumo_agregado) > MAX_TRANSCRIPT_CHARS:
        resumo_agregado = resumo_agregado[:MAX_TRANSCRIPT_CHARS] + "..."

    base["midia"]["transcricoes"] = transcricoes
    base["midia"]["erros"] = erros
    base["midia"]["resumo"] = resumo_agregado
    base["midia"]["processado_em"] = datetime_iso()

    analise.resultado_json = json.dumps(base, ensure_ascii=False)
    db.session.commit()

    return analise


def datetime_iso() -> str:
    try:
        from datetime import datetime
        return datetime.now().isoformat()
    except Exception:
        return ""
