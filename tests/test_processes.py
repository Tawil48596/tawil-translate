from tawil_translate.infrastructure.processes import ProcessInfo, find_remembered_process


def test_remembered_pid_wins_when_still_alive() -> None:
    processes = [ProcessInfo(10, "game.exe"), ProcessInfo(11, "game.exe")]
    assert find_remembered_process(processes, 11, "game.exe") == 11


def test_executable_name_recovers_after_restart() -> None:
    processes = [ProcessInfo(42, "game.exe")]
    assert find_remembered_process(processes, 10, "GAME.EXE") == 42


def test_missing_process_returns_no_selection() -> None:
    assert find_remembered_process([], 10, "game.exe") == 0
