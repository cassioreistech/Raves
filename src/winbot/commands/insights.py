"""O que o WinBot aprendeu sobre você — 100% local, editável e apagável."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from winbot.core import database
from winbot.core.learner import BehaviorLearner, parse_context

app = typer.Typer(help="Perfil, rotinas e recomendações aprendidas localmente.")
console = Console()

_WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")


@app.command("profile")
def insights_profile() -> None:
    """Exibe interesses, horários mais ativos e rotinas aprendidas."""
    interests = database.get_interest_profile(limit=10)
    hours = database.get_active_hours(limit=4)
    routines = database.get_routines()

    interests_table = Table(title="Interesses (peso com decaimento)", border_style="cyan")
    interests_table.add_column("Categoria", style="bold white")
    interests_table.add_column("Palavra-chave")
    interests_table.add_column("Peso", justify="right", style="green")
    interests_table.add_column("Última vez", style="dim")
    for item in interests:
        interests_table.add_row(
            item["category"],
            item["keyword"],
            f"{item['effective_weight']:.2f}",
            str(item["last_seen"])[:10],
        )
    console.print(interests_table if interests else "[yellow]Nenhum interesse ainda.[/yellow]")

    hours_table = Table(title="Horários mais ativos", border_style="cyan")
    hours_table.add_column("Faixa", style="bold white")
    hours_table.add_column("Eventos", justify="right", style="green")
    for item in hours:
        hours_table.add_row(item["hour_bucket"], str(item["total"]))
    console.print(hours_table if hours else "[yellow]Nenhum evento de atividade ainda.[/yellow]")

    routines_table = Table(title="Rotinas aprendidas", border_style="cyan")
    routines_table.add_column("Contexto")
    routines_table.add_column("Confiança", justify="right", style="green")
    routines_table.add_column("Obs.", justify="right")
    routines_table.add_column("Ações", overflow="fold")
    for item in routines:
        dow, bucket = parse_context(item["trigger_context"])
        routines_table.add_row(
            f"{_WEEKDAYS[dow]} · {bucket}",
            f"{item['confidence']:.0%}",
            str(item["times_observed"]),
            ", ".join(item["suggested_actions"][:3]),
        )
    console.print(
        routines_table if routines else "[yellow]Nenhuma rotina consolidada ainda.[/yellow]"
    )

    console.print(
        f"[dim]{database.count_activity_events()} evento(s) de atividade · "
        f"banco {database.db_path()}[/dim]"
    )
    console.print(
        "[dim]Observador: WINBOT_OBSERVER_DISABLED=1 desliga · "
        "'winbot insights forget' apaga tudo.[/dim]"
    )


@app.command("suggest")
def insights_suggest() -> None:
    """Roda a análise de padrões e exibe recomendações personalizadas."""
    learner = BehaviorLearner()
    count = learner.analyze_patterns()
    console.print(f"[dim]{count} padrão(ões) consolidado(s).[/dim]")
    for tip in learner.get_recommendations():
        console.print(f"  [cyan]•[/cyan] {escape(tip)}")


@app.command("forget")
def insights_forget() -> None:
    """Apaga todos os dados de observação e aprendizado (comando de privacidade)."""
    database.purge_observer_data()
    console.print("[bold yellow]Dados de observação e aprendizado apagados.[/bold yellow]")
