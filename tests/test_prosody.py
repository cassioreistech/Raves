from raves.engine.prosody import prepare_speech_text


def test_converte_siglas_e_termos_tecnicos() -> None:
    text = prepare_speech_text("Abra o VS Code e o Chrome, CPU a 90%, RAM cheia, gere um PDF")
    assert "vê ésse côde" in text
    assert "crôme" in text
    assert "cê pê ú" in text
    assert "memória ran" in text
    assert "pê dê éfe" in text


def test_converte_whatsapp_e_wifi() -> None:
    text = prepare_speech_text("Abra o WhatsApp e conecte no Wi-Fi")
    assert "uátizápi" in text
    assert "uai fai" in text


def test_limpa_caminhos_e_markdown() -> None:
    text = prepare_speech_text("Veja C:\\Users\\cassi\\file.txt e **importante** `code`")
    assert "arquivo" in text
    assert "*" not in text
    assert "`" not in text


def test_insere_pausas_em_blocos_longos() -> None:
    long_text = "palavra " * 20
    result = prepare_speech_text(long_text.strip())
    assert "," in result


def test_texto_vazio() -> None:
    assert prepare_speech_text("") == ""
    assert prepare_speech_text("   ") == ""
