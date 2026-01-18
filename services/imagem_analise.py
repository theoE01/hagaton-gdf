import os
import json
import re
from typing import Dict, Any, List, Tuple

from flask import current_app

from models import db, Submission, File, SubmissionAnalise

# OCR libs
from PIL import Image

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    import cv2  # opcional
    import numpy as np
except Exception:
    cv2 = None
    np = None


# -------------------------
# Utilidades
# -------------------------

def _abs_path(rel_path: str) -> str:
    """Converte 'static/uploads/x.png' para path absoluto no projeto."""
    rel = (rel_path or "").replace("\\", "/").lstrip("/")
    return os.path.abspath(os.path.join(current_app.root_path, rel))


def _is_image(mime: str, file_type: str, filename: str) -> bool:
    mime = (mime or "").lower()
    file_type = (file_type or "").lower()
    fn = (filename or "").lower()
    return (
        file_type == "imagem"
        or mime.startswith("image/")
        or fn.endswith((".jpg", ".jpeg", ".png", ".webp"))
    )


def _safe_json_loads(s: str, fallback=None):
    try:
        return json.loads(s)
    except Exception:
        return fallback if fallback is not None else {}


def _clean_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _preprocess_for_ocr_pil(img: Image.Image) -> Image.Image:
    """
    Pré-processamento simples com Pillow (sem OpenCV).
    Converte para escala de cinza e aumenta contraste.
    """
    img = img.convert("L")  # grayscale
    # threshold simples
    img = img.point(lambda x: 0 if x < 160 else 255, mode="1")
    return img


def _preprocess_for_ocr_cv2(img_path: str):
    """
    Pré-processamento melhor com OpenCV (se disponível).
    Retorna uma imagem (numpy) pronta para o Tesseract.
    """
    if cv2 is None or np is None:
        return None

    img = cv2.imread(img_path)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # redução de ruído + binarização adaptativa
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    th = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31, 2
    )
    return th


def _tesseract_config() -> str:
    """
    Configuração OCR (pt + en). Ajuste se quiser só pt.
    """
    langs = os.getenv("OCR_LANGS", "por+eng")
    psm = os.getenv("OCR_PSM", "6")  # 6 = bloco uniforme de texto
    oem = os.getenv("OCR_OEM", "3")  # 3 = default
    return f"-l {langs} --oem {oem} --psm {psm}"


# -------------------------
# Função principal
# -------------------------

def analisar_imagem_e_salvar(submission_id: int) -> Dict[str, Any]:
    """
    Faz OCR das imagens vinculadas à Submission e salva o resultado
    dentro de SubmissionAnalise.resultado_json (sem criar tabela nova).

    Retorna um dict com o resumo do OCR (útil para logs/testes).
    """

    if pytesseract is None:
        raise RuntimeError("OCR indisponível: instale pytesseract e o Tesseract OCR no sistema.")

    sub = Submission.query.get(submission_id)
    if not sub:
        raise RuntimeError(f"Submission {submission_id} não encontrada.")

    files: List[File] = File.query.filter_by(submission_id=sub.id).all()

    imagens = [f for f in files if _is_image(f.mime_type, f.file_type, f.original_name)]
    if not imagens:
        return {"ok": True, "submission_id": sub.id, "ocr": {"imagens": [], "texto_total": ""}}

    resultados = []
    textos = []

    for f in imagens:
        abs_path = _abs_path(f.file_path)
        if not os.path.exists(abs_path):
            resultados.append({
                "file_id": f.id,
                "original_name": f.original_name,
                "path": f.file_path,
                "ok": False,
                "erro": "arquivo_nao_encontrado"
            })
            continue

        try:
            # Se tiver OpenCV, usamos melhor pré-processamento
            if cv2 is not None:
                pre = _preprocess_for_ocr_cv2(abs_path)
                if pre is not None:
                    text = pytesseract.image_to_string(pre, config=_tesseract_config())
                else:
                    img = Image.open(abs_path)
                    img = _preprocess_for_ocr_pil(img)
                    text = pytesseract.image_to_string(img, config=_tesseract_config())
            else:
                img = Image.open(abs_path)
                img = _preprocess_for_ocr_pil(img)
                text = pytesseract.image_to_string(img, config=_tesseract_config())

            text = _clean_text(text)
            textos.append(text)

            resultados.append({
                "file_id": f.id,
                "original_name": f.original_name,
                "path": f.file_path,
                "ok": True,
                "texto": text[:2000]  # guarda preview por arquivo
            })

        except Exception as e:
            current_app.logger.exception(f"OCR falhou para file_id={f.id} submission_id={sub.id}")
            resultados.append({
                "file_id": f.id,
                "original_name": f.original_name,
                "path": f.file_path,
                "ok": False,
                "erro": str(e)[:240]
            })

    texto_total = _clean_text("\n\n".join([t for t in textos if t]))

    # -------------------------
    # Salvar no cache (SubmissionAnalise)
    # -------------------------
    analise = SubmissionAnalise.query.filter_by(submission_id=sub.id).first()
    if not analise:
        # cria cache mínimo se ainda não existe
        analise = SubmissionAnalise(
            submission_id=sub.id,
            user_id=sub.user_id,
            protocolo=(sub.user.protocolo if getattr(sub, "user", None) else ""),
            categoria="não_classificado",
            prioridade="baixa",
            tags_json="[]",
            resumo_curto="",
            resultado_json="{}",
            modelo=None
        )
        db.session.add(analise)
        db.session.flush()

    payload = _safe_json_loads(analise.resultado_json, fallback={})
    payload.setdefault("midia", {})
    payload["midia"]["ocr"] = {
        "texto_total": texto_total[:12000],  # evita JSON gigante
        "imagens": resultados
    }

    analise.resultado_json = json.dumps(payload, ensure_ascii=False)
    db.session.commit()

    return {
        "ok": True,
        "submission_id": sub.id,
        "ocr": {
            "imagens_processadas": len(imagens),
            "texto_total_chars": len(texto_total),
        }
    }
