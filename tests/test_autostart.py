from unittest.mock import patch

from winbot.core import autostart


def test_is_enabled_false_quando_chave_ausente() -> None:
    with patch("winreg.OpenKey", side_effect=FileNotFoundError):
        assert autostart.is_enabled() is False


def test_enable_disable_roundtrip_mockado() -> None:
    store: dict[str, str] = {}

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def open_key(root, path, reserved, access):
        return FakeKey()

    def set_value(key, name, reserved, typ, value):
        store[name] = value

    def query_value(key, name):
        if name not in store:
            raise FileNotFoundError
        return store[name], 1

    def delete_value(key, name):
        if name in store:
            del store[name]
        else:
            raise FileNotFoundError

    with (
        patch("winreg.OpenKey", side_effect=open_key),
        patch("winreg.SetValueEx", side_effect=set_value),
        patch("winreg.QueryValueEx", side_effect=query_value),
        patch("winreg.DeleteValue", side_effect=delete_value),
    ):
        assert autostart.is_enabled() is False
        autostart.enable()
        assert autostart.is_enabled() is True
        assert "tray" in store[autostart.VALUE_NAME]
        autostart.disable()
        assert autostart.is_enabled() is False
