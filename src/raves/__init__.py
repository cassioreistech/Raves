"""RAVES Core — automação e orquestração determinística para Windows."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("raves")
except PackageNotFoundError:  # execução direta do fonte, sem instalação
    __version__ = "0.0.0-dev"

__all__ = ["__version__"]
