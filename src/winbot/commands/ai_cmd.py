"""Gerenciamento do cérebro local (Ollama) — instalação, status, descarga."""

from __future__ import annotations

import shutil
import subprocess
from typing import Annotated

import psutil
import typer
from rich.console import Console

from winbot.ai.local_brain import (
    DEFAULT_MODEL,
    LocalBrain,
    _ollama_executable,
    shutdown_if_managed,
)

app = typer.Typer(help="Cérebro local (Ollama) — status, setup e descarga.")
console = Console()


@app.command("status")
def ai_status() -> None:
    """Mostra se o Ollama está instalado/ativo, o modelo configurado e RAM livre."""
    exe = _ollama_executable()
    brain = LocalBrain()
    available = brain.is_available()
    ram = psutil.virtual_memory()

    console.print(
        f"[bold]Ollama instalado:[/bold] {'✔' if exe else '✘'} {exe or '(não encontrado)'}"
    )
    console.print(f"[bold]Servidor ativo:[/bold] {'✔' if available else '✘'} (localhost:11434)")
    console.print(f"[bold]Modelo configurado:[/bold] {brain.model}")
    free_gb = ram.available / (1024**3)
    total_gb = ram.total / (1024**3)
    console.print(f"[bold]RAM livre:[/bold] {free_gb:.2f} GB de {total_gb:.2f} GB")

    if not exe:
        console.print("[yellow]Rode 'winbot ai setup' para instalar.[/yellow]")
    elif not available:
        console.print("[yellow]Servidor parado. Será iniciado sob demanda.[/yellow]")


def _run_subprocess_streaming(argv: list[str], label: str) -> int:
    """Executa um comando mostrando a saída em tempo real."""
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if line:
            console.print(f"[dim]{line}[/dim]")
    process.wait()
    return process.returncode


@app.command("setup")
def ai_setup(
    lite: Annotated[
        bool, typer.Option("--lite", help="Usa qwen2.5:0.5b (397 MB, PCs com 4 GB de RAM).")
    ] = False,
) -> None:
    """Instala o Ollama (se necessário) e baixa o modelo ultra-compacto."""
    model = "qwen2.5:0.5b" if lite else DEFAULT_MODEL
    exe = _ollama_executable()

    if exe is None:
        console.print("[yellow]Ollama não encontrado. Tentando instalar via winget...[/yellow]")
        winget = shutil.which("winget")
        if winget is None:
            console.print(
                "[bold red]winget não disponível. Instale o Ollama manualmente em "
                "https://ollama.com/download[/bold red]"
            )
            raise typer.Exit(code=1)
        code = _run_subprocess_streaming(
            [
                winget,
                "install",
                "-e",
                "--id",
                "Ollama.Ollama",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            "winget install Ollama",
        )
        if code != 0:
            console.print(f"[bold red]winget falhou (exit {code}).[/bold red]")
            raise typer.Exit(code=1)
        exe = _ollama_executable()
        if exe is None:
            console.print("[bold red]Ollama instalado mas nao encontrado no PATH.[/bold red]")
            console.print("[bold red]Reinicie o terminal.[/bold red]")
            raise typer.Exit(code=1)
        console.print("[green]Ollama instalado.[/green]")

    console.print(f"[bold cyan]Baixando modelo {model}...[/bold cyan]")
    console.print("[dim]Isso pode levar alguns minutos na primeira vez.[/dim]")
    code = _run_subprocess_streaming([exe, "pull", model], f"ollama pull {model}")
    if code != 0:
        console.print(f"[bold red]Falha ao baixar o modelo (exit {code}).[/bold red]")
        raise typer.Exit(code=1)

    # Persiste a escolha do modelo em settings.yaml.
    try:
        from winbot.core.config import user_config_path

        path = user_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        import yaml

        data = {}
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("ai", {})["model"] = model
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    except Exception as exc:
        console.print(f"[yellow]Não foi possível salvar o modelo em settings.yaml: {exc}[/yellow]")

    console.print(f"[bold green]Setup concluído. Modelo ativo: {model}[/bold green]")


@app.command("unload")
def ai_unload() -> None:
    """Descarrega o modelo da RAM imediatamente (keep_alive=0)."""
    brain = LocalBrain()
    if not brain.is_available():
        console.print("[yellow]Servidor Ollama não está ativo.[/yellow]")
        return
    # Envia uma requisição vazia com keep_alive 0 para descarregar.
    import json
    import urllib.request

    payload = json.dumps({"model": brain.model, "prompt": "", "keep_alive": 0}).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0):
            pass
        console.print("[green]Modelo descarregado da RAM.[/green]")
    except Exception as exc:
        console.print(f"[bold red]Falha ao descarregar: {exc}[/bold red]")
        raise typer.Exit(code=1) from exc


@app.command("shutdown")
def ai_shutdown() -> None:
    """Encerra o ollama serve se foi o WinBot que o iniciou."""
    shutdown_if_managed()
    console.print("[dim]Servidor gerenciado encerrado (se aplicável).[/dim]")
