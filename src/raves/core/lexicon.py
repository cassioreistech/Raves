"""Motor léxico rápido (Etapa 10, 100% offline, O(1)).

Normaliza linguagem coloquial para comandos canônicos sem alterar argumentos
entre aspas. Usa dict/set com lookup O(1) e unicodedata para comparação
accent-insensitive sem mutar o texto original.
"""

from __future__ import annotations

import random
import re
import unicodedata

# ---------------------------------------------------------------------------
# Famílias verbais -> verbo canônico do dispatcher
# ---------------------------------------------------------------------------
VERB_MAP: dict[str, str] = {
    # OPEN
    "abrir": "abrir",
    "abre": "abrir",
    "abra": "abrir",
    "iniciar": "abrir",
    "inicia": "abrir",
    "inicie": "abrir",
    "rodar": "abrir",
    "roda": "abrir",
    "executar": "abrir",
    "executa": "abrir",
    "lançar": "abrir",
    "lancar": "abrir",
    "lança": "abrir",
    "lanca": "abrir",
    "subir": "abrir",
    # CLOSE
    "fechar": "fechar",
    "fecha": "fechar",
    "feche": "fechar",
    "encerrar": "fechar",
    "encerra": "fechar",
    "encurre": "fechar",
    "matar": "fechar",
    "mata": "fechar",
    "sair": "fechar",
    "finalizar": "fechar",
    "finalize": "fechar",
    # FOCUS
    "focar": "focar",
    "foce": "focar",
    "mostrar": "focar",
    "mostra": "focar",
    "trazer": "focar",
    "alternar": "focar",
    "ir": "focar",
    # TYPE
    "digitar": "digitar",
    "digita": "digitar",
    "escrever": "digitar",
    "escreve": "digitar",
    "inserir": "digitar",
    "insere": "digitar",
    "colar": "digitar",
    # VOLUME
    "volume": "volume",
    "som": "volume",
    "audio": "volume",
    "áudio": "volume",
    "aumentar": "aumentar",
    "aumenta": "aumentar",
    "sobe": "aumentar",
    "diminuir": "diminuir",
    "diminui": "diminuir",
    "baixar": "diminuir",
    "baixa": "diminuir",
    "desce": "diminuir",
    "mutar": "mutar",
    "muta": "mutar",
    "desmutar": "desmutar",
    "desmuta": "desmutar",
    # SCREENSHOT
    "capturar": "capturar",
    "captura": "capturar",
    "foto": "tirar",
    "screenshot": "tirar",
    # READ
    "ler": "ler",
    "leia": "ler",
    "resumir": "resumir",
    "resuma": "resumir",
    # MEDIA
    "pausar": "pausar",
    "pausa": "pausar",
    "continuar": "continuar",
    "continua": "continuar",
    "proxima": "proxima",
    "próxima": "proxima",
    "anterior": "anterior",
    # MISC
    "tocar": "tocar",
    "bota": "tocar",
    "colocar": "tocar",
    "preparar": "preparar",
    "prepara": "preparar",
    "limpar": "limpar",
    "limpa": "limpar",
}

# ---------------------------------------------------------------------------
# Sinônimos de entidades do Windows
# ---------------------------------------------------------------------------
ENTITY_MAP: dict[str, str] = {
    "navegador": "chrome",
    "browser": "chrome",
    "editor": "code",
    "vscode": "code",
    "vs code": "code",
    "planilha": "excel",
    "texto": "notepad",
    "bloco de notas": "notepad",
    "pasta": "explorer",
    "explorador": "explorer",
    "calculadora": "calc",
}

# ---------------------------------------------------------------------------
# Substituições em nível de frase (antes do word-level)
# ---------------------------------------------------------------------------
_PHRASE_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\btira\s+um\s+print\b", re.IGNORECASE), "tirar print"),
    (re.compile(r"\btira\s+print\b", re.IGNORECASE), "tirar print"),
    (re.compile(r"\btirar\s+print\b", re.IGNORECASE), "tirar print"),
    (re.compile(r"\btira\s+uma?\s+screenshot\b", re.IGNORECASE), "tirar print"),
    (re.compile(r"\bsobe\s+o\s+som\s+pra\s+(\d+)\s*%?", re.IGNORECASE), r"volume em \1%"),
    (re.compile(r"\bsobe\s+o\s+som\b", re.IGNORECASE), "aumentar volume"),
    (re.compile(r"\bbaixa\s+o\s+som\b", re.IGNORECASE), "diminuir volume"),
    (re.compile(r"\bleia\s+arquivo\b", re.IGNORECASE), "ler arquivo"),
    (re.compile(r"\bresuma\s+arquivo\b", re.IGNORECASE), "resumir arquivo"),
    (re.compile(r"\bme\s+avisa\s+em\b", re.IGNORECASE), "me avisa em"),
]


def _strip_accents(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )


def normalize_to_canonical(text: str) -> str:
    """Normaliza um pedido para a forma canônica, preservando argumentos entre aspas.

    Multiplica a cobertura de vocabulário sem aumentar complexidade: famílias
    verbais e sinônimos de entidades são mapeados para os comandos que o
    dispatcher já entende.
    """
    if not text:
        return text
    # Preserva trechos entre aspas (índices ímpares do split).
    parts = re.split(r"(\"[^\"]*\"|\'[^\']*\')", text)
    out: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            out.append(part)
            continue
        value = part
        for pattern, replacement in _PHRASE_REPLACEMENTS:
            value = pattern.sub(replacement, value)
        tokens = value.split()
        new_tokens: list[str] = []
        for token in tokens:
            # lookup accent-insensitive, mas preserva o token original se não mapeado
            key = token.lower().strip(".,!?")
            if key in VERB_MAP:
                new_tokens.append(VERB_MAP[key])
            elif key in ENTITY_MAP:
                new_tokens.append(ENTITY_MAP[key])
            else:
                new_tokens.append(token)
        value = " ".join(new_tokens)
        value = re.sub(r"\s+", " ", value).strip()
        out.append(value)
    return " ".join(part for part in out if part).strip()


# ---------------------------------------------------------------------------
# Respostas naturais variadas (evita robótica repetitiva no TTS/HUD)
# ---------------------------------------------------------------------------
_REPLY_TEMPLATES: dict[str, list[str]] = {
    "volume": ["Volume ajustado para {detail}.", "Pronto, volume em {detail}.", "Feito: {detail}."],
    "mute": ["Mudo alternado.", "Som {detail}.", "Ok, {detail}."],
    "media": ["Mídia: {detail}.", "Controle de mídia: {detail}.", "Feito: {detail}."],
    "screenshot": [
        "Captura salva em {detail}.",
        "Print tirado: {detail}.",
        "Screenshot em {detail}.",
    ],
    "reminder": ["Lembrete agendado: {detail}.", "Vou te avisar: {detail}.", "Agendado: {detail}."],
    "read": ["{detail}", "Li o documento: {detail}", "Conteúdo: {detail}."],
    "abrir": ["Abrindo {detail}.", "{detail} aberto.", "Pronto, {detail}."],
    "fechar": ["Fechando {detail}.", "{detail} encerrado.", "Ok, {detail} fechado."],
    "focar": ["Focando {detail}.", "{detail} em primeiro plano.", "Pronto."],
    "tocar": ["Tocando {detail}.", "Colocando {detail} para tocar.", "Música: {detail}."],
    "generic": ["{detail}", "Pronto: {detail}.", "Feito: {detail}."],
}


def humanize_reply(action_type: str, detail: str) -> str:
    """Gera uma resposta natural variada para evitar repetição robótica."""
    templates = _REPLY_TEMPLATES.get(action_type, _REPLY_TEMPLATES["generic"])
    template = random.choice(templates)
    try:
        return template.format(detail=detail)
    except (KeyError, ValueError):
        return f"{detail}"
