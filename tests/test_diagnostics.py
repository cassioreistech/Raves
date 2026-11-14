from raves.core import diagnostics


def test_capture_error_snapshot_grava_txt_e_tenta_screenshot(tmp_path, mocker) -> None:
    mocker.patch.object(diagnostics, "CRASH_REPORTS_DIR", tmp_path / "crash")
    mocker.patch("pyautogui.screenshot", side_effect=RuntimeError("sem display"))

    path = diagnostics.capture_error_snapshot("contexto teste", "boom")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "contexto teste" in content
    assert "boom" in content
    assert not path.with_suffix(".png").exists()


def test_capture_error_snapshot_salva_screenshot_quando_disponivel(tmp_path, mocker) -> None:
    mocker.patch.object(diagnostics, "CRASH_REPORTS_DIR", tmp_path / "crash")
    fake_image = mocker.MagicMock()
    mocker.patch("pyautogui.screenshot", return_value=fake_image)

    path = diagnostics.capture_error_snapshot("ctx", "err")
    assert path.exists()
    fake_image.save.assert_called_once()
