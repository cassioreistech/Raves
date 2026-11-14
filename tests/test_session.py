from raves.core.session import SessionContext, get_session


def test_session_singleton_e_reset() -> None:
    a = get_session()
    b = get_session()
    assert a is b
    a.update_target("calc.exe")
    a.update_window("Calculadora")
    a.set_entity("last_text", "ola")
    assert b.last_target_app == "calc.exe"
    assert b.get_entity("last_text") == "ola"

    a.reset()
    assert a.last_target_app is None
    assert a.last_window_title is None
    assert a.last_entities == {}


def test_session_ignora_valores_vazios() -> None:
    session = SessionContext()
    session.update_target("")
    session.update_window(None)
    assert session.last_target_app is None
    assert session.last_window_title is None
