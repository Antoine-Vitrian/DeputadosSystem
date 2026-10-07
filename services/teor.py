import io
import re

import requests
from pypdf import PdfReader

from services.camara import explain_project

USER_AGENT = "RadarLegislativo/1.0"
NOISE = re.compile(
    r"(\*CD\d+\*|Autenticado Eletronicamente[^\n]*|Apresenta[cç][aã]o:[^\n]*|"
    r"P[ÁA]GINA \d+|^\d+$|phfm/\S+)",
    re.IGNORECASE | re.MULTILINE,
)


def _download_teor(url):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=40)
    response.raise_for_status()
    return response.content, response.headers.get("content-type", "")


def _pdf_text(payload):
    reader = PdfReader(io.BytesIO(payload))
    chunks = []
    for page in reader.pages[:12]:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def _html_text(payload):
    text = payload.decode("utf-8", errors="ignore")
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    return re.sub(r"<[^>]+>", " ", text)


def extract_teor_text(url):
    payload, content_type = _download_teor(url)
    if "pdf" in content_type or payload[:4] == b"%PDF":
        return _pdf_text(payload)
    return _html_text(payload)


def _clean(text):
    text = NOISE.sub(" ", text)
    text = text.replace("\xa0", " ").replace("\u00ad", "")
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _sentences(text, limit=3):
    pieces = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))
    chosen = []
    for piece in pieces:
        piece = piece.strip()
        if len(piece) < 50:
            continue
        if re.search(r"entra em vigor|faço saber|excelentíssim", piece, re.I):
            continue
        chosen.append(piece)
        if len(chosen) >= limit:
            break
    return chosen


def summarize_from_teor(raw_text, project):
    text = _clean(raw_text or "")
    if len(text) < 80:
        return explain_project(project)
    split = re.search(r"JUSTIFICA(?:ÇÃO|TIVA)\b", text, re.I)
    body = text[: split.start()] if split else text[:2000]
    reason = text[split.end() :] if split else ""
    first = _sentences(body, 2)
    if not first and project.title:
        first = [f"O {project.code} {project.title.rstrip('.')}."]
    second = _sentences(reason, 2)
    if not second:
        leftover = _sentences(body, 4)
        second = leftover[2:] or leftover[-1:]
    paragraph_one = " ".join(first) or f"O {project.code} {project.title.rstrip('.')}."
    paragraph_two = " ".join(second) or "O inteiro teor não traz uma justificação separada além do que já está no texto dispositivo."
    return f"{paragraph_one}\n\n{paragraph_two}"


def ensure_text_summary(project, force=False):
    if project.text_summary and not force:
        return project
    if not project.full_text_url:
        project.text_summary = explain_project(project)
        project.save(update_fields=["text_summary"])
        return project
    try:
        raw = extract_teor_text(project.full_text_url)
        project.text_summary = summarize_from_teor(raw, project)
    except (requests.RequestException, ValueError, OSError):
        project.text_summary = explain_project(project)
    project.save(update_fields=["text_summary"])
    return project
