from __future__ import annotations

import csv
import io
import subprocess
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
    """List interactive Windows processes without requiring psutil."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH", "/V"],
        check=True,
        capture_output=True,
        text=True,
        encoding="mbcs",
        errors="replace",
        creationflags=flags,
    )
    processes: list[ProcessInfo] = []
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) < 9 or not row[1].isdigit():
            continue
        processes.append(ProcessInfo(int(row[1]), row[0], row[8]))
    return sorted(processes, key=lambda item: (item.name.casefold(), item.pid))


def find_remembered_process(processes: list[ProcessInfo], pid: int | None, name: str | None) -> int:
    if pid is not None and any(item.pid == pid for item in processes):
        return pid
    if name:
        match = next((item for item in processes if item.name.casefold() == name.casefold()), None)
        if match:
            return match.pid
    return 0
