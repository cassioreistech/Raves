"""Alvo mínimo para provar que Nuitka compila as dependências nativas."""

import pywinauto
import win32api
import win32com

print(
    "winbot native imports OK:", win32api.GetComputerName(), win32com.__name__, pywinauto.__name__
)
