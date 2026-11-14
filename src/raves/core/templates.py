"""Workflows de fábrica instalados quando ~/.raves/workflows está vazio (Etapa 8)."""

from __future__ import annotations

from pathlib import Path

TEMPLATES: dict[str, str] = {
    "modo_foco.yaml": """name: Modo Foco
description: Fecha distrações comuns e abre o editor/terminal.
steps:
  - name: Fechar navegador
    action: kill_process
    params: { name: chrome.exe }
    continue_on_error: true
  - name: Fechar Discord
    action: kill_process
    params: { name: discord.exe }
    continue_on_error: true
  - name: Abrir VS Code
    action: launch_app
    params: { target: code.exe }
""",
    "limpeza_rapida.yaml": """name: Limpeza Rápida
description: Limpa arquivos temporários e mostra status de memória/disco.
steps:
  - name: Limpar temp
    action: clean_temp
  - name: Status do sistema
    action: powershell
    params: { command: "Get-ComputerInfo | Select-Object CsName, OsName" }
""",
    "bom_dia.yaml": """name: Bom Dia
description: Saudação proativa + abertura do navegador/ambiente de trabalho.
steps:
  - name: Abrir navegador
    action: launch_app
    params: { target: chrome.exe }
    continue_on_error: true
  - name: Status
    action: powershell
    params: { command: "Get-Date" }
""",
    "organizar_downloads.yaml": """name: Organizar Downloads
description: Organiza arquivos soltos da pasta Downloads em subpastas.
steps:
  - name: Organizar por tipo
    action: powershell
    params:
      command: |
        $d = Join-Path $env:USERPROFILE 'Downloads'
        Get-ChildItem $d -File | ForEach-Object {
          $ext = $_.Extension.ToLower()
          $sub = switch ($ext) {
            '.pdf' { 'Documentos' }
            '.docx' { 'Documentos' }
            '.xlsx' { 'Documentos' }
            '.png' { 'Imagens' }
            '.jpg' { 'Imagens' }
            '.jpeg' { 'Imagens' }
            '.exe' { 'Instaladores' }
            '.msi' { 'Instaladores' }
            default { 'Outros' }
          }
          $dest = Join-Path $d $sub
          New-Item -ItemType Directory -Force -Path $dest | Out-Null
          Move-Item $_.FullName $dest -Force
        }
""",
}


def install_default_templates() -> int:
    """Instala os templates de fábrica se a pasta de workflows estiver vazia."""
    directory = Path.home() / ".raves" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.glob("*.yaml")):
        return 0
    written = 0
    for name, content in TEMPLATES.items():
        (directory / name).write_text(content, encoding="utf-8")
        written += 1
    return written
