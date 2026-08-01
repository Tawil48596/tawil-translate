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
