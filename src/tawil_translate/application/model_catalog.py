from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class STTProfile:
    id: str
    label: str
    model: str
    device: str
    compute_type: str
    approximate_vram_gb: float
    use_case: str
    approximate_download_gb: float = 0.0


PROFILES: tuple[STTProfile, ...] = (
    STTProfile("cpu", "CPU / 兼容", "base", "cpu", "int8", 0.0, "无独立显卡、低功耗设备", 0.15),
    STTProfile("fast", "极速", "small", "cuda", "int8_float16", 1.2, "动作游戏、最低延迟", 0.5),
    STTProfile("balanced", "均衡（推荐）", "medium", "cuda", "float16", 2.8, "大多数游戏和直播", 1.5),
    STTProfile(
        "accurate",
        "高精度",
        "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "cuda",
        "float16",
        5.5,
        "剧情游戏、多口音内容",
        1.6,
    ),
)


def get_profile(profile_id: str) -> STTProfile:
    try:
        return next(profile for profile in PROFILES if profile.id == profile_id)
    except StopIteration as exc:
        choices = ", ".join(profile.id for profile in PROFILES)
        raise ValueError(f"unknown STT profile {profile_id!r}; choose: {choices}") from exc


def recommend_profile(vram_gb: float | None, cuda_available: bool) -> STTProfile:
    if not cuda_available or not vram_gb:
        return get_profile("cpu")
    if vram_gb >= 6.5:
        return get_profile("accurate")
    if vram_gb >= 3.5:
        return get_profile("balanced")
    return get_profile("fast")
