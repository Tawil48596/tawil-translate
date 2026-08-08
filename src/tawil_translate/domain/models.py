from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import monotonic


class HealthState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    WORKING = "working"
    ERROR = "error"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class AudioFrame:
    pcm: bytes
    sample_rate: int
    channels: int
    captured_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.captured_at:
            object.__setattr__(self, "captured_at", monotonic())


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    audio: bytes
    sample_rate: int
    started_at: float
    ended_at: float
    committed: bool = True


@dataclass(frozen=True, slots=True)
class Transcript:
    utterance_id: str
    text: str
    language: str | None = None
    committed: bool = True


@dataclass(frozen=True, slots=True)
class SubtitleEvent:
    utterance_id: str
    source_text: str
    translated_text: str
    is_final: bool
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class HealthEvent:
    component: str
    state: HealthState
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MetricEvent:
    name: str
    value: float
    unit: str
