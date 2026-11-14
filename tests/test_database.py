from winbot.core import database


def test_init_cria_tabelas() -> None:
    database.init_db()
    with database._connect() as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {
        "installed_apps",
        "command_history",
        "activity_events",
        "user_interests",
        "learned_routines",
        "app_meta",
    } <= tables


def test_pragmas_wal_e_synchronous_normal_em_toda_conexao() -> None:
    database.init_db()
    for _ in range(2):
        with database._connect() as conn:
            mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            sync = int(conn.execute("PRAGMA synchronous").fetchone()[0])
        assert mode == "wal"
        assert sync == 1  # NORMAL


def test_upsert_find_exato_like_e_update() -> None:
    assert database.upsert_apps([]) == 0
    database.upsert_apps(
        [
            ("Google Chrome", r"C:\long\chrome.lnk", "start_menu_all"),
            ("googlechrome", r"C:\short\chrome.exe", "start_menu_all"),
            ("notepad", r"C:\win\notepad.exe", "app_paths_hklm"),
        ]
    )
    assert database.count_apps() == 3
    # Nomes sao normalizados para minusculo.
    assert database.find_app("google chrome") == r"C:\long\chrome.lnk"
    # LIKE escolhe o nome MAIS CURTO que contem o termo.
    assert database.find_app("chrom") == r"C:\short\chrome.exe"
    assert database.find_app("inexistente_xyz") is None

    # Exato tem prioridade sobre LIKE.
    database.upsert_apps([("chrome", r"C:\exact\chrome.exe", "app_paths_hkcu")])
    assert database.find_app("chrome") == r"C:\exact\chrome.exe"
    # Upsert atualiza target_path/source sem duplicar.
    database.upsert_apps([("chrome", r"C:\new\chrome.exe", "app_paths_hklm")])
    assert database.count_apps() == 4
    row = database.get_apps("chrome")[0]
    assert database.find_app("chrome") == r"C:\new\chrome.exe"
    assert row["source"] == "app_paths_hklm"
    assert row["updated_at"]


def test_get_apps_com_filtro() -> None:
    database.upsert_apps(
        [
            ("google chrome", r"C:\a\chrome.exe", "start_menu_all"),
            ("notepad", r"C:\b\notepad.exe", "app_paths_hklm"),
        ]
    )
    assert [row["name"] for row in database.get_apps("chrome")] == ["google chrome"]
    assert len(database.get_apps()) == 2


def test_log_command_e_get_last_successful_ignora_memoria() -> None:
    database.log_command("abrir calc", True, "OK")
    database.log_command("ps Remove-Item", False, "BLOQUEADO")
    database.log_command("repetir ultimo", True, "reexecutando")
    database.log_command("historico", True, "5 linhas")

    assert database.get_last_successful_command() == "abrir calc"


def test_get_recent_history_ordem_limite_e_formato() -> None:
    for index in range(12):
        database.log_command(f"cmd {index}", index % 2 == 0, f"msg {index}")

    rows = database.get_recent_history(limit=5)
    assert len(rows) == 5
    assert rows[0]["raw_command"] == "cmd 11"
    assert rows[-1]["raw_command"] == "cmd 7"
    assert set(rows[0]) == {
        "id",
        "raw_command",
        "success",
        "result_message",
        "executed_at",
    }
    assert isinstance(rows[0]["success"], bool)
    assert len(database.get_recent_history()) == 10
    assert len(database.get_recent_history(limit=0)) == 1


def test_is_memory_command() -> None:
    assert database.is_memory_command("repetir ultimo")
    assert database.is_memory_command("HISTÓRICO")
    assert database.is_memory_command("últimos comandos")
    assert not database.is_memory_command("abrir calc")
