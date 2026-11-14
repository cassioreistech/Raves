"""Leitor local de documentos (Etapa 9, 100% offline).

Suporta .pdf (pypdf), .docx (python-docx) e .txt/.md/.csv/.json.
Lazy imports: pypdf e python-docx só são carregados ao ler o respectivo formato.
"""

from __future__ import annotations

from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".csv", ".json"}


def extract_document_text(file_path: Path | str, max_chars: int = 4000) -> str:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Formato não suportado: {suffix}")

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        from docx import Document

        doc = Document(str(path))
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")

    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def count_pages(file_path: Path | str) -> int:
    path = Path(file_path)
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    return 1


def summarize_document(file_path: Path | str) -> str:
    path = Path(file_path)
    text = extract_document_text(path, max_chars=4000)
    if not text.strip():
        return "Documento vazio ou sem texto extraível."

    word_count = len(text.split())
    pages = count_pages(path)

    # Tenta resumo via LLM local (Ollama).
    try:
        from raves.ai.local_brain import LocalBrain

        brain = LocalBrain()
        if brain.is_available():
            reply = brain.ask(f"Resuma em 3 frases o texto a seguir:\n{text[:3000]}")
            if reply.get("text"):
                return f"Resumo ({pages} pág., {word_count} palavras): {reply['text']}"
    except Exception:
        pass

    preview = " ".join(text.split()[:60])
    return f"Prévia ({pages} pág., {word_count} palavras): {preview}…"
