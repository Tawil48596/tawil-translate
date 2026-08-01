import pytest

from tawil_translate.application.model_catalog import get_profile, recommend_profile


def test_profile_recommendation_tracks_available_hardware() -> None:
    assert recommend_profile(None, False).id == "cpu"
    assert recommend_profile(2.0, True).id == "fast"
    assert recommend_profile(4.0, True).id == "balanced"
    assert recommend_profile(8.0, True).id == "accurate"


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError):
        get_profile("huge")
