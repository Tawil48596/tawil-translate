from __future__ import annotations

from dataclasses import dataclass, field

from tawil_translate.domain.models import SpeechSegment


@dataclass(slots=True)
class SmartChunker:
    """Merge short speech fragments while enforcing a hard latency ceiling."""

    merge_gap_ms: int = 260
    min_seconds: float = 0.45
    max_seconds: float = 8.0
    _pending: list[SpeechSegment] = field(default_factory=list)

    def push(self, segment: SpeechSegment) -> list[SpeechSegment]:
        if not self._pending:
            if self._duration(segment) >= self.min_seconds:
                return [segment]
            self._pending.append(segment)
            return self._drain_if_long()
        previous = self._pending[-1]
        gap_ms = max(0.0, segment.started_at - previous.ended_at) * 1000
        if gap_ms <= self.merge_gap_ms:
            self._pending.append(segment)
            if self._pending_duration() >= self.min_seconds:
                return self.flush()
            return self._drain_if_long()
        output = self.flush()
        self._pending.append(segment)
        return output + self._drain_if_long()

    def flush(self) -> list[SpeechSegment]:
        if not self._pending:
            return []
        result = self._merge(self._pending)
        self._pending = []
        return [result]

    def _drain_if_long(self) -> list[SpeechSegment]:
        return self.flush() if self._pending_duration() >= self.max_seconds else []

    def _pending_duration(self) -> float:
        if not self._pending:
            return 0.0
        return self._pending[-1].ended_at - self._pending[0].started_at

    @staticmethod
    def _duration(segment: SpeechSegment) -> float:
        return max(segment.ended_at - segment.started_at, len(segment.audio) / 2 / segment.sample_rate)

    @staticmethod
    def _merge(segments: list[SpeechSegment]) -> SpeechSegment:
        first, last = segments[0], segments[-1]
        return SpeechSegment(b"".join(item.audio for item in segments), first.sample_rate, first.started_at, last.ended_at)
