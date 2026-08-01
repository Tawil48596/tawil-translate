from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    name: str
    window_title: str = ""

    @property
    def label(self) -> str:
        suffix = f" — {self.window_title}" if self.window_title and self.window_title != "N/A" else ""
        return f"{self.name} ({self.pid}){suffix}"


def list_processes() -> list[ProcessInfo]:
    """Return only processes with an active Windows render-audio session."""
    try:
        import comtypes
        from pycaw.constants import AudioSessionState
        from pycaw.pycaw import AudioUtilities
    except ImportError as exc:
        raise RuntimeError("pycaw is required to discover audio processes") from exc

    active_state = AudioSessionState.Active.value
    try:
        sessions = AudioUtilities.GetAllSessions()
    except (OSError, comtypes.COMError) as exc:
        raise RuntimeError("Windows 当前没有可用的音频输出设备") from exc
    return _active_processes(sessions, active_state)


def _active_processes(sessions, active_state: int = 1) -> list[ProcessInfo]:
    processes: dict[int, ProcessInfo] = {}
    for session in sessions:
        try:
            if session.State != active_state or not session.ProcessId:
                continue
            process = session.Process
            if process is None:
                continue
            processes[session.ProcessId] = ProcessInfo(session.ProcessId, process.name())
        except (OSError, RuntimeError):
            # A process may exit between session enumeration and name lookup.
            continue
    return sorted(processes.values(), key=lambda item: (item.name.casefold(), item.pid))


def find_remembered_process(processes: list[ProcessInfo], pid: int | None, name: str | None) -> int:
    if pid is not None and any(item.pid == pid for item in processes):
        return pid
    if name:
        match = next((item for item in processes if item.name.casefold() == name.casefold()), None)
        if match:
            return match.pid
    return 0
