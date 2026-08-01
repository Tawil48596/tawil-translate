from tawil_translate.application.chunking import SmartChunker
from tawil_translate.domain.models import SpeechSegment


def _segment(text: bytes, start: float, end: float) -> SpeechSegment:
    return SpeechSegment(text, 16_000, start, end)


def test_short_adjacent_segments_are_merged() -> None:
    chunker = SmartChunker(merge_gap_ms=260)
    assert chunker.push(_segment(b"a", 0.0, 0.3)) == []
    assert chunker.push(_segment(b"b", 0.4, 0.7)) == []
    output = chunker.flush()
    assert output[0].audio == b"ab"


def test_gap_commits_previous_utterance() -> None:
    chunker = SmartChunker(merge_gap_ms=200)
    chunker.push(_segment(b"first", 0.0, 0.4))
    output = chunker.push(_segment(b"next", 0.8, 1.0))
    assert output[0].audio == b"first"
