from tawil_translate.application.model_catalog import get_profile
from tawil_translate.application.model_manager import LocalModelManager
from tawil_translate.paths import model_root


def test_model_is_ready_only_with_required_files(tmp_path) -> None:
    profile = get_profile("fast")
    manager = LocalModelManager(tmp_path)
    path = manager.path_for(profile)
    path.mkdir()
    assert not manager.is_downloaded(profile)
    (path / "model.bin").write_bytes(b"model")
    assert not manager.is_downloaded(profile)
    (path / "config.json").write_text("{}", encoding="utf-8")
    assert manager.is_downloaded(profile)


def test_relative_model_root_is_anchored_to_working_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    assert model_root("models") == tmp_path / "models"
