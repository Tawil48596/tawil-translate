from tawil_translate.domain.config import AppConfig


def test_config_round_trip(tmp_path) -> None:
    path = tmp_path / "user_config.json"
    config = AppConfig()
    config.stt.profile = "fast"
    config.save(path)
    assert AppConfig.load(path).stt.profile == "fast"


def test_new_config_has_download_fallback_and_translation_prompt() -> None:
    config = AppConfig()
    assert config.stt.download_source == "auto"
    assert "{target_language}" in config.translation.custom_prompt
    assert "{glossary}" in config.translation.custom_prompt


def test_legacy_short_chunks_are_migrated_for_complete_sentences(tmp_path) -> None:
    path = tmp_path / "user_config.json"
    path.write_text(
        '{"vad":{"min_silence_ms":280,"min_speech_ms":180},'
        '"pipeline":{"max_segment_seconds":5}}',
        encoding="utf-8",
    )

    config = AppConfig.load(path)

    assert config.vad.min_silence_ms == 450
    assert config.vad.min_speech_ms == 200
    assert config.pipeline.max_segment_seconds == 12.0
