"""Gancho de voz 100% offline (modo texto).

IMPORTANTE: não há ASR/TTS nem API externa aqui — isso exigiria modelo ou nuvem e
contrariaria o requisito offline. ``voice listen`` é o ponto de integração: liga o
observador de contexto, exibe a saudação proativa e abre o mesmo loop de pedidos.
Captura/síntese de voz reais ficam para uma etapa futura.
"""

from __future__ import annotations

from typing import Annotated

import typer

from winbot.commands._interactive import interactive_loop
from winbot.core.config import load_settings

app = typer.Typer(help="Escuta por voz (hoje: modo texto, sem dependências externas).")


@app.command("listen")
def voice_listen(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simula todos os pedidos desta sessão."),
    ] = False,
) -> None:
    """Inicia a escuta (texto), com observador e sugestão proativa na abertura."""
    interactive_loop(
        prompt="winbot voz >",
        header=(
            "[bold cyan]WinBot Voice · modo texto[/bold cyan] [dim]- sem ASR/TTS, "
            "sem nuvem. 'sair' encerra.[/dim]"
        ),
        dry_run=dry_run,
        settings=load_settings(),
    )
