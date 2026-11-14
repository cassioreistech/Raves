from winbot.engine import vision


def test_read_screen_text_usa_ocr_unificado(mocker) -> None:
    mocker.patch.object(vision, "_capture", return_value=(object(), (0, 0)))
    mocker.patch.object(vision, "_ocr", return_value=([], "Ola mundo"))
    assert vision.read_screen_text() == "Ola mundo"


def test_read_screen_text_com_regiao(mocker) -> None:
    captured = {}

    def fake_capture(region):
        captured["region"] = region
        return (object(), (10, 20))

    mocker.patch.object(vision, "_capture", side_effect=fake_capture)
    mocker.patch.object(vision, "_ocr", return_value=([], "texto"))
    assert vision.read_screen_text((10, 20, 100, 50)) == "texto"
    assert captured["region"] == (10, 20, 100, 50)


def test_find_text_on_screen_palavra_unica(mocker) -> None:
    words = [{"text": "Cinco", "x": 10, "y": 20, "w": 30, "h": 15}]
    mocker.patch.object(vision, "_capture", return_value=(object(), (5, 7)))
    mocker.patch.object(vision, "_ocr", return_value=(words, "Cinco"))
    assert vision.find_text_on_screen("cinco") == (5 + 10 + 15, 7 + 20 + 7)


def test_find_text_on_screen_frase(mocker) -> None:
    words = [
        {"text": "Bloco", "x": 0, "y": 0, "w": 10, "h": 10},
        {"text": "de", "x": 12, "y": 0, "w": 5, "h": 10},
        {"text": "Notas", "x": 19, "y": 0, "w": 10, "h": 10},
    ]
    mocker.patch.object(vision, "_capture", return_value=(object(), (0, 0)))
    mocker.patch.object(vision, "_ocr", return_value=(words, "Bloco de Notas"))
    assert vision.find_text_on_screen("bloco de notas") == (14, 5)


def test_find_text_on_screen_retorna_none_quando_ausente(mocker) -> None:
    mocker.patch.object(vision, "_capture", return_value=(object(), (0, 0)))
    mocker.patch.object(vision, "_ocr", return_value=([], ""))
    assert vision.find_text_on_screen("inexistente") is None


def test_click_text_clica_quando_encontra(mocker) -> None:
    mocker.patch.object(vision, "find_text_on_screen", return_value=(100, 200))
    click = mocker.patch("pyautogui.click")
    ok, message = vision.click_text("OK")
    assert ok is True
    click.assert_called_once_with(100, 200)
    assert "OK" in message


def test_click_text_falha_quando_nao_encontra(mocker) -> None:
    mocker.patch.object(vision, "find_text_on_screen", return_value=None)
    ok, message = vision.click_text("nada")
    assert ok is False
    assert "não encontrado" in message
