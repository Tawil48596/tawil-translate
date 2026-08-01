from tawil_translate.domain.config import AppConfig


def test_config_round_trip(tmp_path) -> None:
    path = tmp_path / "user_config.json"
    config = AppConfig()
    config.stt.profile = "fast"
    config.save(path)
    assert AppConfig.load(path).stt.profile == "fast"
