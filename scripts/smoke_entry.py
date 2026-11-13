"""Alvo mínimo: prova que Nuitka compila as dependências nativas do Passo 3."""

import cryptography
import pyautogui
import pyperclip
import pywinauto
import win32api
import win32com

print(
    "winbot native imports OK:",
    win32api.GetComputerName(),
    pyautogui.__name__,
    pyperclip.__name__,
    pywinauto.__name__,
    win32com.__name__,
    cryptography.__version__,
)
