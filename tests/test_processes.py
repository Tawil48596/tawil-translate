from tawil_translate.infrastructure.processes import (
    ProcessInfo,
    _active_processes,
    find_remembered_process,
)


class _Process:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


class _Session:
    def __init__(self, pid: int, name: str, state: int) -> None:
        self.ProcessId = pid
        self.Process = _Process(name)
        self.State = state


def test_remembered_pid_wins_when_still_alive() -> None:
    processes = [ProcessInfo(10, "game.exe"), ProcessInfo(11, "game.exe")]
    assert find_remembered_process(processes, 11, "game.exe") == 11


def test_executable_name_recovers_after_restart() -> None:
    processes = [ProcessInfo(42, "game.exe")]
    assert find_remembered_process(processes, 10, "GAME.EXE") == 42


def test_missing_process_returns_no_selection() -> None:
    assert find_remembered_process([], 10, "game.exe") == 0


def test_only_active_audio_sessions_are_listed_and_deduplicated() -> None:
    sessions = [
        _Session(20, "silent.exe", 0),
        _Session(30, "game.exe", 1),
        _Session(30, "game.exe", 1),
        _Session(40, "expired.exe", 2),
    ]
    assert _active_processes(sessions) == [ProcessInfo(30, "game.exe")]
