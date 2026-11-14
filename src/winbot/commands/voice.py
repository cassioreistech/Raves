"""Gancho de voz 100% offline (modo texto + calibração).

IMPORTANTE: não há ASR/TTS nem API externa aqui — isso exigiria modelo ou nuvem e
contrariaria o requisito offline. ``voice listen`` é o ponto de integração: liga o
observador de contexto, exibe a saudação proativa e abre o mesmo loop de pedidos.
Captura/síntese de voz reais ficam para uma etapa futura.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from winbot.commands._interactive import interactive_loop
from winbot.core import database
from winbot.core.config import load_settings
from winbot.engine.audio_pipeline import ResilientAudioCapture
from winbot.engine.voice import VoiceEngine

app = typer.Typer(help="Escuta por voz (hoje: modo texto, sem dependências externas).")
console = Console()


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
            "[bold cyan]WinBot Voice[/bold cyan] [dim]- ASR/TTS quando o modelo "
            "Whisper estiver disponível; 'sair' encerra.[/dim]"
        ),
        dry_run=dry_run,
        settings=load_settings(),
        voice_mode=True,
    )


@app.command("calibrate")
def voice_calibrate() -> None:
    """Testa a captura resiliente, monta o initial_prompt e lista o aprendizado fonético."""
    console.print("[bold cyan]WinBot Voice · calibração[/bold cyan]")

    capture = ResilientAudioCapture()
    try:
        capture.start()
        capture.calibrate(duration=0.5)
        console.print(f"[green]Piso de ruído calibrado:[/green] {capture._noise_floor:.4f}")
        console.print("[dim]Captura de 3s para medir VAD...[/dim]")
        pcm = capture.record_utterance(timeout=3.0)
        if pcm:
            console.print(f"[green]Fala capturada:[/green] {len(pcm)} bytes de PCM")
        else:
            console.print(
                "[yellow]Nenhuma fala detectada em 3s (ok se você ficou em silêncio).[/yellow]"
            )
    except Exception as exc:
        console.print(f"[bold red]Falha na captura:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        capture.stop()

    engine = VoiceEngine()
    prompt = engine.build_initial_prompt()
    short = prompt[:200] + ("..." if len(prompt) > 200 else "")
    console.print(f"[dim]Initial prompt ({len(prompt)} chars):[/dim] {short}")

    corrections = database.get_speech_corrections()
    vocab = database.get_custom_vocab()
    table = Table(title="Aprendizado fonético", border_style="cyan")
    table.add_column("Ouvido", style="bold white")
    table.add_column("Mapeado para", style="green")
    table.add_column("Hits", justify="right")
    for row in corrections:
        table.add_row(str(row["heard_phrase"]), str(row["mapped_phrase"]), str(row["hits"]))
    console.print(table if corrections else "[dim]Nenhuma correção fonética ainda.[/dim]")
    console.print(f"[dim]Vocabulário customizado: {', '.join(vocab) if vocab else '(vazio)'}[/dim]")
    console.print("[green]Calibração concluída.[/green]")
