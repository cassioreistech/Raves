import pytest

from winbot.core.security import SecurityViolationError
from winbot.engine import gui


def test_click_at_dry_run_nao_clica(mocker) -> None:
    mocker.patch("winbot.engine.windows_api.screen_size", return_value=(1920, 1080))
    pag = mocker.patch("winbot.engine.gui._pyautogui")
    assert gui.click_at(100, 200, dry_run=True) == "simulado"
    pag.assert_not_called()


def test_click_at_fora_da_tela_bloqueia(mocker) -> None:
    mocker.patch("winbot.engine.windows_api.screen_size", return_value=(1920, 1080))
    with pytest.raises(SecurityViolationError, match="fora da tela"):
        gui.click_at(9999, 200)


def test_hotkey_proibida_bloqueia() -> None:
    with pytest.raises(SecurityViolationError, match="proibida"):
        gui.hotkey(["ctrl", "alt", "delete"])


def test_tecla_invalida_bloqueia() -> None:
    with pytest.raises(SecurityViolationError, match="não permitida"):
        gui.hotkey(["f13"])


def test_type_text_nao_loga_conteudo(mocker) -> None:
    audit_mock = mocker.patch("winbot.engine.gui.audit")
    segredo = "senha-super-secreta"
    assert gui.type_text_safe(segredo, dry_run=True) == "simulado"
    assert segredo not in str(audit_mock.call_args)


def test_click_image_arquivo_inexistente(tmp_path) -> None:
    with pytest.raises(SecurityViolationError, match="não encontrada"):
        gui.click_image(str(tmp_path / "nope.png"))


def test_click_image_dry_run_com_arquivo_valido(tmp_path, mocker) -> None:
    image = tmp_path / "btn.png"
    image.write_bytes(b"fake")
    pag = mocker.patch("winbot.engine.gui._pyautogui")
    assert gui.click_image(str(image), dry_run=True) == "simulado"
    pag.assert_not_called()
