"""Sessão interativa compartilhada por ``shell`` e ``voice listen``.

Mantém num único lugar: renderização dos resultados, gate de licença, bootstrap
do observador de contexto, saudação proativa e o loop de pedidos.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt

from raves.core.config import Settings
from raves.core.dispatcher import DispatchResult, execute_natural_command
from raves.core.learner import BehaviorLearner
from raves.core.licensing import LicenseError, check_license_or_raise
from raves.engine.observer import ContextObserver

console = Console()


def build_intro_greeting() -> str:
    """Saudação inicial premium baseada no horário do dia."""
    from datetime import datetime

    hour = datetime.now().hour
    if 5 <= hour < 12:
        prefix = "Bom dia"
    elif 12 <= hour < 18:
        prefix = "Boa tarde"
    else:
        prefix = "Boa noite"
    return f"{prefix}! Estou à sua disposição. Serei seu novo agente e amigo."


def speak_text(text: str) -> None:
    """Fala um texto via pyttsx3 em background (best-effort, nunca bloqueia)."""
    if not text or not text.strip():
        return

    def _worker() -> None:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            with contextlib.suppress(Exception):
                engine.setProperty("rate", 165)
            engine.say(text)
            engine.runAndWait()
            with contextlib.suppress(Exception):
                engine.stop()
        except Exception:
            pass

    import threading

    threading.Thread(target=_worker, name="raves-intro-tts", daemon=True).start()


def status_icons() -> tuple[str, str]:
    """✔/✘ em UTF-8; fallback ASCII em console cp1252 (ver PLAN.md §7)."""
    encoding = (getattr(console.file, "encoding", "") or "").lower().replace("-", "")
    return ("✔", "✘") if "utf" in encoding else ("OK", "X")


def render_results(results: list[DispatchResult]) -> None:
    ok_icon, bad_icon = status_icons()
    for item in results:
        good = item.ok and not item.blocked
        icon = ok_icon if good else bad_icon
        color = "green" if good else "red"
        prefix = "BLOQUEADO: " if item.blocked else ""
        console.print(
            f"  [{color}]{icon}[/{color}] [bold]{escape(item.label)}[/bold] "
            f"[dim]{escape(prefix + item.message)}[/dim]"
        )


def enforce_license(settings: Settings) -> None:
    """Mesmo gate comercial de ``workflow run``."""
    if not settings.licensing.enabled:
        return
    try:
        check_license_or_raise()
    except LicenseError as exc:
        console.print(f"[bold red]Licença:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc


def start_observer() -> ContextObserver | None:
    """Liga a telemetria passiva. Retorna None se desligada por env."""
    if os.environ.get("RAVES_OBSERVER_DISABLED"):
        return None
    observer = ContextObserver()
    observer.start_background_watch()
    console.print(
        "[dim]Observador de contexto ativo (dados só neste computador). "
        "RAVES_OBSERVER_DISABLED=1 desliga · 'insights forget' apaga tudo.[/dim]"
    )
    return observer


def show_proactive_greeting() -> str | None:
    """Consolida padrões e exibe a sugestão, se houver (nunca executa nada)."""
    learner = BehaviorLearner()
    learner.analyze_patterns()
    greeting = learner.get_proactive_greeting()
    if greeting:
        console.print(Panel(escape(greeting), title="Sugestão", border_style="cyan"))
    return greeting


def interactive_loop(
    *,
    prompt: str,
    header: str,
    dry_run: bool,
    settings: Settings,
    voice_mode: bool = False,
    confirm_fn: Any = None,
) -> None:
    """Loop de pedidos com observer + saudação na abertura e parada limpa.

    Em ``voice_mode=True`` tenta usar ``VoiceEngine`` (ASR/TTS). Se o modelo
    Whisper não estiver disponível localmente ou o microfone falhar, cai para
    o modo texto sem derrubar a sessão.
    """
    enforce_license(settings)
    observer = start_observer()
    engine = None
    if voice_mode and not os.environ.get("RAVES_DISABLE_ASR"):
        try:
            from raves.engine.voice import VoiceEngine

            engine = VoiceEngine()
            engine.start()
            if engine._get_model() is None:
                console.print(
                    "[yellow]Modelo Whisper não encontrado localmente. Usando modo texto.[/yellow]"
                )
                engine.stop()
                engine = None
                console.print("[dim]Modo texto (sem ASR/TTS).[/dim]")
            else:
                console.print("[dim]Modo voz ativo. Fale ou digite 'sair'.[/dim]")
        except Exception as exc:
            console.print(f"[yellow]Voz indisponível ({exc}); usando modo texto.[/yellow]")
            engine = None
    if voice_mode and engine is None:
        console.print("[dim]Modo texto (sem ASR/TTS).[/dim]")

    _confirm = confirm_fn
    if _confirm is None:

        def _confirm(prompt: str) -> bool:
            answer = Prompt.ask(f"{prompt} [s/N]", console=console, default="n")
            return answer.strip().lower() in {"s", "sim", "y", "yes", "pode", "confirmo", "ok"}

    # Voz: confirmação por voz.
    if voice_mode and engine is not None:

        def _voice_confirm(prompt: str) -> bool:
            engine.speak(prompt + "? Confirma?")
            reply = engine.listen_once()
            if reply is None:
                return False
            lowered = reply.lower()
            positive = any(
                tok in lowered for tok in ("sim", "pode", "confirmo", "yes", "ok", "claro")
            )
            negative = any(tok in lowered for tok in ("não", "nao", "cancela", "negativo"))
            return positive and not negative

        _confirm = _voice_confirm

    try:
        console.print(header)
        intro = build_intro_greeting()
        console.print(f"[bold cyan]{intro}[/bold cyan]")
        speak_text(intro)
        greeting = show_proactive_greeting()
        if engine is not None and greeting:
            engine.speak(greeting)

        while True:
            try:
                if engine is not None:
                    console.print("[dim]Ouvindo...[/dim]")
                    pedido = engine.listen_once()
                    if pedido is None:
                        continue
                    pedido = pedido.strip()
                else:
                    pedido = Prompt.ask(prompt, console=console).strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if not pedido:
                continue
            if pedido.casefold() in {"sair", "exit", "quit"}:
                break
            results = execute_natural_command(
                pedido,
                apply=not dry_run,
                policy=settings.security,
                confirm_fn=_confirm if not dry_run else None,
            )
            render_results(results)
            if engine is not None:
                if any(not item.ok or item.blocked for item in results):
                    engine.speak("Pedido interrompido.")
                else:
                    engine.speak(f"{len(results)} ação concluída.")
    finally:
        if engine is not None:
            engine.stop()
        if observer is not None:
            observer.stop()
    console.print("[dim]Até logo.[/dim]")
