"""Executor de rotinas em lote definidas em YAML.

DRY-RUN é o padrão: nenhuma ação com efeito colateral ocorre sem --apply.
Uma violação de segurança aborta a rotina mesmo com continue_on_error=true.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from winbot.core.config import WorkflowDefinition, load_settings
from winbot.core.dispatcher import execute_step as _execute_step
from winbot.core.licensing import LicenseError, check_license_or_raise
from winbot.core.logger import logger

app = typer.Typer(help="Gerencia e executa rotinas automatizadas (Workflows YAML).")
console = Console()

# Sem mkdir no import: `winbot --help` não deve criar diretórios.
WORKFLOWS_DIR = Path.home() / ".winbot" / "workflows"


# Execução centralizada em core/dispatcher.py: uma única implementação das travas
# de segurança para `workflow run`, `winbot do` e `winbot shell`.
# Reexportado para manter a API usada pelos testes existentes.


def _resolve_path(name: str) -> Path:
    direct = Path(name)
    return direct if direct.exists() else WORKFLOWS_DIR / f"{name}.yaml"


@app.command("run")
def run_workflow(
    name: Annotated[
        str,
        typer.Argument(help="Nome do YAML em ~/.winbot/workflows ou caminho completo."),
    ],
    apply: Annotated[
        bool, typer.Option("--apply", help="Executa de fato (padrão: simulação).")
    ] = False,
) -> None:
    """Executa um workflow de automação. DRY-RUN é o padrão."""
    file_path = _resolve_path(name)
    if not file_path.exists():
        console.print(
            f"[bold red]Erro:[/bold red] Workflow não encontrado em [yellow]{file_path}[/yellow]"
        )
        raise typer.Exit(code=1)

    try:
        raw_data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        wf = WorkflowDefinition.model_validate(raw_data)
    except (ValidationError, ValueError, yaml.YAMLError) as exc:
        console.print(f"[bold red]Erro de validação no YAML:[/bold red]\n{exc}")
        raise typer.Exit(code=2) from exc

    settings = load_settings()
    if settings.licensing.enabled:
        try:
            check_license_or_raise()
        except LicenseError as exc:
            console.print(f"[bold red]Licença:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    console.print(
        Panel(f"[bold cyan]{wf.name}[/bold cyan]\n[dim]{wf.description}[/dim]", expand=False)
    )
    logger.info(f"Iniciando workflow: {wf.name} (dry_run={not apply})")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for idx, step in enumerate(wf.steps, start=1):
            task = progress.add_task(f"[{idx}/{len(wf.steps)}] {step.name}...", total=None)
            outcome = _execute_step(step, policy=settings.security, dry_run=not apply)
            progress.remove_task(task)

            # Símbolos ASCII: consoles Windows cp1252 não conseguem codificar ✔/✘.
            if outcome.blocked:
                console.print(
                    f"  [red]X[/red] [bold]{step.name}[/bold] -> "
                    f"[red]BLOQUEADO: {outcome.message}[/red]"
                )
                console.print(
                    "[bold red]Workflow abortado: violação de segurança "
                    "(continue_on_error é ignorado).[/bold red]"
                )
                raise typer.Exit(code=1)

            if outcome.ok:
                console.print(
                    f"  [green]OK[/green] [bold]{step.name}[/bold] [dim]({outcome.message})[/dim]"
                )
            else:
                console.print(
                    f"  [red]X[/red] [bold]{step.name}[/bold] -> [red]{outcome.message}[/red]"
                )
                if not step.continue_on_error:
                    console.print("[bold red]Workflow abortado devido a erro.[/bold red]")
                    raise typer.Exit(code=1)

    console.print("\n[bold green]Workflow concluído com sucesso![/bold green]")


@app.command("list")
def list_workflows() -> None:
    """Lista os workflows disponíveis na pasta do usuário."""
    files = sorted(WORKFLOWS_DIR.glob("*.yaml")) if WORKFLOWS_DIR.exists() else []
    if not files:
        console.print(f"[yellow]Nenhum workflow encontrado em {WORKFLOWS_DIR}[/yellow]")
        return
    console.print(f"[bold]Workflows em {WORKFLOWS_DIR}:[/bold]")
    for file in files:
        console.print(f"• [bold cyan]{file.stem}[/bold cyan] [dim]({file})[/dim]")
