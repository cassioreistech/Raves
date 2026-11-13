from winbot import __version__
from winbot.main import app


def test_pacote_importa() -> None:
    assert __version__ != "0.0.0-dev"


def test_help(runner) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "sys" in result.stdout
    assert "version" in result.stdout


def test_version(runner) -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_sys_status(runner, mocker) -> None:
    """Não depende de hardware real: psutil é mockado."""

    class _Mem:
        percent = 42.0
        used = 4 * 1024**3
        total = 16 * 1024**3

    class _Disk:
        percent = 55.0
        free = 100 * 1024**3

    mocker.patch("winbot.commands.system.psutil.cpu_percent", return_value=12.5)
    mocker.patch("winbot.commands.system.psutil.cpu_count", return_value=8)
    mocker.patch("winbot.commands.system.psutil.virtual_memory", return_value=_Mem())
    mocker.patch("winbot.commands.system.psutil.disk_usage", return_value=_Disk())

    result = runner.invoke(app, ["sys", "status"])
    assert result.exit_code == 0
    assert "CPU" in result.stdout
