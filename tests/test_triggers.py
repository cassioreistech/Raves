import threading

from raves.engine.triggers import TriggerManager, TriggerRule


def test_trigger_rule_validacao() -> None:
    rule = TriggerRule(
        name="pdf", event="file_created", path="C:/x", extensions=[".pdf"], run="org"
    )
    assert rule.extensions == [".pdf"]
    assert rule.debounce_seconds == 1.5


def test_manager_add_remove_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RAVES_DB_PATH", str(tmp_path / "t.db"))
    triggers_file = tmp_path / "triggers.yaml"
    monkeypatch.setattr("raves.engine.triggers.TRIGGERS_FILE", triggers_file)

    manager = TriggerManager(rules=[])
    manager.add(
        TriggerRule(
            name="a", event="file_created", path=str(tmp_path), extensions=[".pdf"], run="x"
        )
    )
    manager.add(TriggerRule(name="b", event="window_opened", window_title="Calc", run="y"))
    assert len(manager.list_rules()) == 2
    assert manager.remove("a") is True
    assert manager.remove("a") is False
    assert len(manager.list_rules()) == 1
    assert triggers_file.exists()


def test_file_created_debounce_dispara_apos_debounce(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAVES_DB_PATH", str(tmp_path / "t.db"))
    triggers_file = tmp_path / "triggers.yaml"
    monkeypatch.setattr("raves.engine.triggers.TRIGGERS_FILE", triggers_file)

    fired: list[tuple[str, str]] = []
    manager = TriggerManager(rules=[])
    manager.set_executor(lambda rule, ctx: fired.append((rule.name, ctx)))
    rule = TriggerRule(
        name="pdf",
        event="file_created",
        path=str(tmp_path),
        extensions=[".pdf"],
        run="x",
        debounce_seconds=0.05,
    )
    manager.add(rule)
    manager.start()

    # Simula evento via handler diretamente.
    from raves.engine.triggers import _FileHandler

    handler = _FileHandler(manager, rule)
    fake_event = type("E", (), {"is_directory": False, "src_path": str(tmp_path / "a.pdf")})()
    handler.on_created(fake_event)
    # debounce: ainda nao disparou
    assert fired == []
    threading.Event().wait(0.2)
    assert len(fired) == 1
    assert fired[0][0] == "pdf"

    manager.stop()


def test_file_created_filtra_extensao(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAVES_DB_PATH", str(tmp_path / "t.db"))
    triggers_file = tmp_path / "triggers.yaml"
    monkeypatch.setattr("raves.engine.triggers.TRIGGERS_FILE", triggers_file)

    fired: list[str] = []
    manager = TriggerManager(rules=[])
    manager.set_executor(lambda rule, ctx: fired.append(rule.name))
    rule = TriggerRule(
        name="pdf",
        event="file_created",
        path=str(tmp_path),
        extensions=[".pdf"],
        run="x",
        debounce_seconds=0.05,
    )
    manager.add(rule)
    manager.start()

    from raves.engine.triggers import _FileHandler

    handler = _FileHandler(manager, rule)
    fake_txt = type("E", (), {"is_directory": False, "src_path": str(tmp_path / "a.txt")})()
    handler.on_created(fake_txt)
    threading.Event().wait(0.2)
    assert fired == []

    manager.stop()


def test_window_opened_dispara_na_transicao(monkeypatch, tmp_path, mocker) -> None:
    monkeypatch.setenv("RAVES_DB_PATH", str(tmp_path / "t.db"))
    triggers_file = tmp_path / "triggers.yaml"
    monkeypatch.setattr("raves.engine.triggers.TRIGGERS_FILE", triggers_file)

    fired: list[str] = []
    manager = TriggerManager(rules=[])
    manager.set_executor(lambda rule, ctx: fired.append(rule.name))
    rule = TriggerRule(name="calc", event="window_opened", window_title="Calc", run="x")
    manager.add(rule)

    titles = iter(["Calculadora", "Calculadora", "Bloco de Notas"])
    mocker.patch("win32gui.GetForegroundWindow", return_value=1)
    mocker.patch("win32gui.GetWindowText", side_effect=lambda h: next(titles, "x"))

    manager.start()
    threading.Event().wait(2.5)
    manager.stop()

    assert fired.count("calc") == 1  # nao repete enquanto a janela nao muda
