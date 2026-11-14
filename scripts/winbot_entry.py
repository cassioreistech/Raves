"""Ponto de entrada do build Nuitka (Passo 4).

Nuitka compila um *script*, nao um ``console_script`` do setuptools. Este arquivo e o
equivalente a ``winbot = winbot.main:app``: configura o encoding antes de qualquer
import do Typer/Rich (console legado do Windows usa cp1252) e delega a CLI.
"""

from __future__ import annotations

import sys


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    from winbot.main import app

    app()


if __name__ == "__main__":
    main()
