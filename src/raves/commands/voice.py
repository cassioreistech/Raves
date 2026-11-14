"""Gancho de voz offline (ASR/TTS reais + calibração + treino fonético)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from raves.commands._interactive import interactive_loop
from raves.core import database
from raves.core.config import load_settings
from raves.engine.audio_pipeline import ResilientAudioCapture
from raves.engine.tts import get_gender, set_gender, setup_tts_model, speak_text
from raves.engine.voice import VoiceEngine

app = typer.Typer(help="Escuta por voz (ASR/TTS offline, sem dependências de nuvem).")
console = Console()


@app.command("listen")
def voice_listen(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simula todos os pedidos desta sessão."),
    ] = False,
) -> None:
    """Inicia a escuta (ASR/TTS reais quando o modelo Whisper está em cache)."""
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
    console.print(f"[dim]Voz atual: {get_gender()}[/dim]")
    console.print("[green]Calibração concluída.[/green]")


@app.command("set-voice")
def voice_set_voice(
    gender: Annotated[str, typer.Argument(help="masculina ou feminina")],
) -> None:
    """Escolhe a voz do TTS (masculina/feminina)."""
    try:
        set_gender(gender)
    except ValueError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=2) from exc
    console.print(f"[green]Voz definida como '{gender}'.[/green]")
    console.print(f"[dim]Voz ativa agora: {get_gender()}[/dim]")


@app.command("test")
def voice_test() -> None:
    """Fala uma frase de teste com a voz atual (valida TTS)."""
    gender = get_gender()
    sample = "Bom dia! Estou à sua disposição. Serei seu novo agente e amigo."
    console.print(f"[dim]Testando voz '{gender}'...[/dim]")
    speak_text(sample, gender=gender)
    console.print("[green]Fala enviada ao TTS.[/green]")


@app.command("setup-tts")
def voice_setup_tts() -> None:
    """Baixa o modelo Piper (pt-BR, masculino, neural) para TTS offline de alta qualidade."""
    console.print("[bold cyan]Baixando modelo Piper pt-BR (faber, ~60 MB)...[/bold cyan]")
    ok, message = setup_tts_model()
    if ok:
        console.print(f"[green]{message}[/green]")
    else:
        console.print(f"[bold red]{message}[/bold red]")
        raise typer.Exit(code=1)
