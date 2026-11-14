from pathlib import Path

from typer.testing import CliRunner

from winbot.core import database
from winbot.core.config import SecuritySettings
from winbot.core.dispatcher import (
    _policy_for,
    _resolve_app_name,
    execute_natural_command,
    parse_instruction,
    redact_command,
)
from winbot.main import app

CHAIN = "abrir calc e esperar 1 segundos e fechar calc"


def test_parse_cadeia_completa() -> None:
    specs = parse_instruction(CHAIN)
    assert [spec.step.action for spec in specs] == ["launch_app", "wait", "kill_process"]
    assert specs[0].step.params["target"] == "calc.exe"
    assert specs[2].step.params["name"] == [
        "calc.exe",
        "calculator.exe",
        "calculatorapp.exe",
    ]
    assert specs[1].step.params["seconds"] == 1.0


def test_e_dentro_do_texto_nao_quebra_a_cadeia() -> None:
    specs = parse_instruction("digitar Joao e Maria")
    assert len(specs) == 1
    assert specs[0].step.params["text"] == "Joao e Maria"


def test_digitar_com_enter_gera_dois_passos_e_nao_vaza_texto() -> None:
    specs = parse_instruction("digitar senha123 com enter")
    assert [spec.step.action for spec in specs] == ["gui_type", "gui_hotkey"]
    assert specs[0].step.params["text"] == "senha123"
    assert specs[1].step.params["keys"] == ["enter"]
    assert "senha123" not in specs[0].label


def test_atalho_aceita_mais_e_espaco() -> None:
    assert parse_instruction("atalho ctrl+c")[0].step.params["keys"] == ["ctrl", "c"]
    assert parse_instruction("atalho ctrl + v")[0].step.params["keys"] == ["ctrl", "v"]


def test_limpar_temp_focar_e_ps() -> None:
    assert parse_instruction("limpar temp")[0].step.action == "clean_temp"
    assert parse_instruction("focar Calculadora")[0].step.params["title"] == "Calculadora"
    assert parse_instruction("ps Get-Process")[0].step.params["command"] == "Get-Process"


def test_esperar_respeita_limite_do_schema() -> None:
    results = execute_natural_command("esperar 999 segundos", apply=False)
    assert results[0].ok is False


def test_comando_desconhecido_e_pedido_vazio() -> None:
    assert "nao reconhecido" in execute_natural_command("dancar samba", apply=False)[0].message
    assert execute_natural_command("   ", apply=False)[0].ok is False


def test_kill_process_com_lista_de_aliases_soma(mocker) -> None:
    from winbot.core.config import WorkflowStep
    from winbot.core.dispatcher import execute_step

    kill = mocker.patch("winbot.engine.windows_api.kill_process_by_name", return_value=1)
    step = WorkflowStep(name="fechar", action="kill_process", params={"name": ["a.exe", "b.exe"]})
    outcome = execute_step(step, policy=SecuritySettings(), dry_run=True)
    assert outcome.ok is True
    assert "2 instancia" in outcome.message
    assert kill.call_count == 2


def test_dry_run_nao_executa_nada(mocker) -> None:
    mocker.patch("winbot.engine.windows_api.launch_app", return_value=True)
    mocker.patch("winbot.engine.windows_api.kill_process_by_name", return_value=1)
    popen = mocker.patch("winbot.engine.windows_api.subprocess.Popen")
    sleep = mocker.patch("winbot.core.dispatcher.time.sleep")

    results = execute_natural_command(CHAIN, apply=False, policy=SecuritySettings())
    assert len(results) == 3
    assert all(item.ok for item in results)
    popen.assert_not_called()
    sleep.assert_not_called()


def test_ps_na_blacklist_e_fail_closed() -> None:
    results = execute_natural_command(
        "ps Remove-Item -Recurse C:\\tmp e abrir calc",
        apply=False,
        policy=SecuritySettings(),
    )
    assert len(results) == 1  # parou antes de 'abrir calc'
    assert results[0].blocked is True
    assert results[0].ok is False


def test_clean_temp_dry_run_nao_apaga(tmp_path: Path, mocker) -> None:
    mocker.patch("winbot.core.dispatcher.tempfile.gettempdir", return_value=str(tmp_path))
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "pasta").mkdir()

    results = execute_natural_command("limpar temp", apply=False, policy=SecuritySettings())
    assert results[0].ok is True
    assert "1 arquivo(s) seriam removidos" in results[0].message
    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "pasta").exists()


def test_clean_temp_apply_remove_so_arquivos_topo(tmp_path: Path, mocker) -> None:
    mocker.patch("winbot.core.dispatcher.tempfile.gettempdir", return_value=str(tmp_path))
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "pasta").mkdir()
    (tmp_path / "pasta" / "b.txt").write_text("y", encoding="utf-8")

    results = execute_natural_command("limpar temp", apply=True, policy=SecuritySettings())
    assert results[0].ok is True
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "pasta" / "b.txt").exists()


def test_do_dry_run_renderiza_icones(mocker) -> None:
    mocker.patch("winbot.engine.windows_api.launch_app", return_value=True)
    mocker.patch("winbot.engine.windows_api.kill_process_by_name", return_value=1)
    result = CliRunner().invoke(app, ["do", CHAIN, "--dry-run"])
    assert result.exit_code == 0, result.stdout
    assert "✔" in result.stdout
    assert "3 ação(ões)" in result.stdout


def test_do_bloqueio_retorna_exit_1() -> None:
    result = CliRunner().invoke(app, ["do", "ps Remove-Item -Recurse C:\\tmp"])
    assert result.exit_code == 1
    assert "✘" in result.stdout
    assert "BLOQUEADO" in result.stdout


def test_do_comando_desconhecido() -> None:
    result = CliRunner().invoke(app, ["do", "dancar samba"])
    assert result.exit_code == 1
    assert "✘" in result.stdout


def test_shell_executa_e_sai_com_exit(mocker) -> None:
    mocker.patch("winbot.engine.windows_api.launch_app", return_value=True)
    result = CliRunner().invoke(app, ["shell", "--dry-run"], input="abrir calc\nsair\n")
    assert result.exit_code == 0, result.stdout
    assert "✔" in result.stdout
    assert "Até logo" in result.stdout


def test_shell_sai_com_exit() -> None:
    result = CliRunner().invoke(app, ["shell"], input="exit\n")
    assert result.exit_code == 0
    assert "Até logo" in result.stdout


# --- Etapa 2 (RPA Nativo UIA) ---------------------------------------------


def test_parse_clicar_em_janela_e_botao_ativo() -> None:
    specs = parse_instruction("clicar em Cinco na janela Calculadora")
    assert specs[0].step.action == "uia_click"
    assert specs[0].step.params == {"window": "Calculadora", "control": "Cinco"}

    specs = parse_instruction("clicar no botao Seis")
    assert specs[0].step.action == "uia_click"
    assert specs[0].step.params["window"] == ""
    assert specs[0].step.params["control"] == "Seis"


def test_parse_esperar_janela() -> None:
    specs = parse_instruction("esperar janela Calculadora")
    assert specs[0].step.action == "wait_window"
    assert specs[0].step.params["title"] == "Calculadora"
    assert specs[0].step.params["timeout"] == 15


def test_uia_click_dry_run_nao_clica(mocker) -> None:
    click = mocker.patch("winbot.engine.uia_engine.click_control", return_value=(True, "ok"))
    results = execute_natural_command(
        "clicar em Cinco na janela Calculadora", apply=False, policy=SecuritySettings()
    )
    assert results[0].ok is True
    click.assert_not_called()


def test_uia_click_falha_gera_snapshot(mocker) -> None:
    mocker.patch(
        "winbot.engine.uia_engine.click_control", return_value=(False, "controle não encontrado")
    )
    snapshot = mocker.patch("winbot.core.dispatcher.capture_error_snapshot")
    results = execute_natural_command(
        "clicar em Inexistente na janela Calculadora", apply=True, policy=SecuritySettings()
    )
    assert results[0].ok is False
    snapshot.assert_called_once()


# --- Etapa 1 de Blindagem: indice, resolucao de nomes e memoria ------------


def test_resolve_app_name_alias_indice_e_raw() -> None:
    assert _resolve_app_name("calc") == "calc.exe"  # APP_ALIASES primeiro
    database.upsert_apps([("chrome", r"C:\apps\chrome.exe", "app_paths_hklm")])
    assert _resolve_app_name("chrome") == r"C:\apps\chrome.exe"
    assert _resolve_app_name("app_inexistente") == "app_inexistente"  # raw puro


def test_abrir_app_indexado_marca_target_para_allowlist() -> None:
    database.upsert_apps([("chrome", r"C:\apps\chrome.exe", "app_paths_hklm")])
    spec = parse_instruction("abrir chrome")[0]
    assert spec.step.params["target"] == r"C:\apps\chrome.exe"
    assert spec.step.params["indexed"] is True

    policy = SecuritySettings()
    enriched = _policy_for([spec], policy)
    assert "chrome.exe" in enriched.allowed_apps
    # A politica original nao e mutada: YAML continua com a allowlist antiga.
    assert policy.allowed_apps == ["notepad.exe", "calc.exe", "explorer.exe"]
    assert _policy_for(parse_instruction("abrir calc"), policy) is policy


def test_redact_command_mascara_texto_de_digitar() -> None:
    assert redact_command("digitar senha123") == "digitar texto (8 caractere(s))"
    assert redact_command("digitar senha123 com enter") == (
        "digitar texto (8 caractere(s)) com enter"
    )
    assert "senha123" not in redact_command("digitar senha123 e abrir calc")
    assert redact_command("abrir calc") == "abrir calc"


def test_log_registra_toda_execucao(mocker) -> None:
    mocker.patch("winbot.engine.windows_api.launch_app", return_value=True)
    execute_natural_command("abrir calc", apply=False, policy=SecuritySettings())
    row = database.get_recent_history()[0]
    assert row["raw_command"] == "abrir calc"
    assert row["success"] is True
    assert "abrir calc.exe" in row["result_message"]


def test_repetir_reexecuta_sem_loop(mocker) -> None:
    mocker.patch("winbot.engine.windows_api.launch_app", return_value=True)
    execute_natural_command("abrir calc", apply=False, policy=SecuritySettings())

    results = execute_natural_command("repetir", apply=False, policy=SecuritySettings())
    assert results[0].label == "repetir"
    assert "Reexecutando" in results[0].message
    assert any("abrir calc.exe" in item.label for item in results)
    # O ultimo sucesso continua sendo o comando real, nao "repetir".
    assert database.get_last_successful_command() == "abrir calc"


def test_repetir_sem_historico() -> None:
    results = execute_natural_command("repetir ultimo", apply=False)
    assert results[0].ok is False
    assert "Nenhum comando anterior" in results[0].message


def test_historico_exibe_ultimos_5() -> None:
    for index in range(7):
        database.log_command(f"abrir calc {index}", True, "OK")
    results = execute_natural_command("ultimos comandos", apply=False)
    assert len(results) == 5
    assert all(item.ok for item in results)
    assert results[0].label.startswith("#")


def test_historico_mascara_senha_no_terminal() -> None:
    database.log_command("digitar senha_super_secreta", True, "OK")
    result = CliRunner().invoke(app, ["do", "historico"])
    assert result.exit_code == 0
    assert "senha_super_secreta" not in result.stdout
    assert "texto (" in result.stdout
