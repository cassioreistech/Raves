"""Contexto de sessão imediato (Etapa 6, 100% em memória).

Rastreia o alvo recente da interação para que referências anafóricas
('fecha ele', 'digitar X' sem janela) funcionem naturalmente. Singleton leve:
nenhum arquivo, nenhum I/O, zero overhead em repouso.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionContext:
    last_target_app: str | None = None
    last_window_title: str | None = None
    last_entities: dict[str, str] = field(default_factory=dict)

    def update_target(self, app: str | None) -> None:
        if app:
            self.last_target_app = app

    def update_window(self, title: str | None) -> None:
        if title:
            self.last_window_title = title

    def set_entity(self, key: str, value: str) -> None:
        self.last_entities[key] = value

    def get_entity(self, key: str) -> str | None:
        return self.last_entities.get(key)

    def reset(self) -> None:
        self.last_target_app = None
        self.last_window_title = None
        self.last_entities.clear()


_instance: SessionContext | None = None


def get_session() -> SessionContext:
    global _instance
    if _instance is None:
        _instance = SessionContext()
    return _instance


# Atalho de módulo para uso direto: ``from raves.core.session import session``.
session = get_session()
