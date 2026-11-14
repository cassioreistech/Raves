"""Pré-processamento de prosódia e pronúncia PT-BR (Etapa de Voz Natural).

Prepara o texto antes da síntese para soar mais humano: converte siglas e
termos técnicos em inglês para escrita fonética natural em português, insere
pausas entre blocos longos e limpa símbolos de markdown/caminhos longos.
100% local, determinístico, sem modelo.
"""

from __future__ import annotations

import re

# Mapa de termos técnicos/siglas -> pronúncia fonética PT-BR.
_PHONETIC: dict[str, str] = {
    "vs code": "vê ésse côde",
    "vscode": "vê ésse côde",
    "cpu": "cê pê ú",
    "ram": "memória ran",
    "wi-fi": "uai fai",
    "wifi": "uai fai",
    "pdf": "pê dê éfe",
    "chrome": "crôme",
    "whatsapp": "uátizápi",
    "excel": "exel",
    "word": "uórd",
    "outlook": "áutluk",
    "windows": "uínndous",
    "linux": "línucs",
    "python": "páiton",
    "github": "guítháb",
    "http": "agá tê tê pê",
    "https": "agá tê tê pê ésse",
    "url": "u ár éle",
    "api": "a pê í",
    "json": "jêison",
    "sql": "ésse quê él",
    "css": "cê ésse ésse",
    "html": "agá tê éme éle",
    "usb": "u ésse bê",
    "ssd": "ésse ésse dê",
    "gpu": "gê pê ú",
    "ai": "a í",
    "ok": "o quê",
    "vs": "vê ésse",
}

# Ordena por comprimento decrescente para casar termos compostos primeiro.
_PHONETIC_KEYS = sorted(_PHONETIC.keys(), key=len, reverse=True)

# Regex única (alternância do mais longo para o mais curto): evita que um termo
# curto (ex: "ai") case em substring de uma substituição já feita (ex: "uai fai").
_PHONETIC_RE = re.compile("|".join(re.escape(key) for key in _PHONETIC_KEYS), re.IGNORECASE)

# Padrão para caminhos de arquivo longos (Windows/Unix).
_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s]+|/(?:[^\s/]+/)+[^\s]+")


def _convert_phonetic(text: str) -> str:
    # Substitui termos de forma case-insensitive em UMA passada (sem re-scan).
    def _replace(match: re.Match[str]) -> str:
        return _PHONETIC.get(match.group(0).lower(), match.group(0))

    return _PHONETIC_RE.sub(_replace, text)


def _clean_symbols(text: str) -> str:
    # Remove markdown básico e caminhos longos (substitui por "arquivo").
    text = _PATH_RE.sub("arquivo", text)
    # Remove marcadores markdown comuns.
    text = re.sub(r"[*_`#>]", "", text)
    # Normaliza múltiplos espaços.
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _insert_pauses(text: str) -> str:
    # Insere vírgula em blocos muito longos sem pontuação (a cada ~12 palavras).
    sentences = re.split(r"([.!?])", text)
    rebuilt: list[str] = []
    for chunk in sentences:
        if not chunk.strip():
            rebuilt.append(chunk)
            continue
        words = chunk.split()
        if len(words) > 14 and "," not in chunk and ";" not in chunk:
            # Insere vírgula a cada 12 palavras.
            new_words: list[str] = []
            for index, word in enumerate(words):
                new_words.append(word)
                if (index + 1) % 12 == 0 and index + 1 < len(words):
                    new_words.append(",")
            chunk = " ".join(new_words)
        rebuilt.append(chunk)
    return "".join(rebuilt)


def prepare_speech_text(text: str) -> str:
    """Prepara texto para síntese de voz natural em PT-BR."""
    if not text:
        return text
    result = _clean_symbols(text)
    result = _convert_phonetic(result)
    result = _insert_pauses(result)
    return result.strip()
