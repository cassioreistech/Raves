"""Reexporta o grupo ``voice`` (mantido por compatibilidade com a spec da Etapa 3).

A implementação vive em ``raves.commands.voice``; este módulo apenas reexporta
o app para não duplicar comandos.
"""

from __future__ import annotations

from raves.commands.voice import app

__all__ = ["app"]
