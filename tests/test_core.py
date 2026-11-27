from __future__ import annotations

import types

from core.commands import parse_override_text, with_quality_reset
from core.platform_profile import resolve_platform
from core.presets import (
    build_ffmpeg_command,
    describe_spec,
    match_preset,
    resolve_spec,
)


def test_preset_aliases():
    assert match_preset("720p") == "720p30"
    assert match_preset("720p_30") == "720p30"
    assert match_preset("有损压缩 720p 30") == "720p30"
    assert match_preset("无损") == "lossless"
    assert match_preset("原画") == "lossless"
    assert match_preset("unknown") is None


def test_parse_simple_and_advanced_overrides():
    assert parse_override_text("720p30") == ({"quality": "720p30"}, None)
    assert parse_override_text("25MB") == ({"target_mb": 25.0}, None)
    assert parse_override_text("720p30 25MB") == (
        {"quality": "720p30", "target_mb": 25.0},
        None,
    )
    assert parse_override_text("crf 22 25MB") == (
        {"crf": 22, "target_mb": 25.0},
        None,
    )
    assert parse_override_text("audio 0") == ({"audio_kbps": 0}, None)
    assert parse_override_text("quality 有损压缩 720p 30") == (
        {"quality": "720p30"},
        None,
    )
    assert parse_override_text("有损压缩 720p 30 25MB") == (
        {"quality": "720p30", "target_mb": 25.0},
        None,
    )
    assert parse_override_text("crf 99")[1] is not None


def test_quality_resets_advanced_fields_in_same_layer():
    spec = resolve_spec(
        "720p30",
        {"crf": 18, "target_mb": 25},
        {"quality": "480p30"},
    )
    assert spec.max_height == 480
    assert spec.crf == 26
    assert spec.target_mb is None


def test_audio_zero_means_silent():
    spec = resolve_spec("720p30", {"audio_kbps": 0})
    assert spec.keep_audio is False


def test_target_size_disables_lossless():
    spec = resolve_spec("无损", {"target_mb": 25})
    assert spec.lossless is False
    assert spec.target_mb == 25


def test_quality_reset_keeps_same_command_advanced_fields():
    current = {"quality": "720p30", "crf": 18, "max_height": 1080}
    updated = with_quality_reset(
        current, {"quality": "480p30", "crf": 22}
    )
    assert updated["quality"] == "480p30"
    assert updated["crf"] == 22
    assert "max_height" not in updated


def test_ffmpeg_command_caps_fps_and_scales_down():
    info = {"width": 1920, "height": 1080, "fps": 60, "duration": 120}
    spec = resolve_spec("720p30")
    cmd = build_ffmpeg_command("in.mp4", "out.mp4", spec, info, False)
    joined = " ".join(cmd)
    assert "scale=w=1280:h=720" in joined
    assert "force_original_aspect_ratio=decrease" in joined
    assert "-r 30" in joined
    assert "-pix_fmt yuv420p" in joined
    assert "+faststart" in joined


def test_ffmpeg_target_size_uses_bitrate():
    info = {"width": 1280, "height": 720, "fps": 30, "duration": 120}
    spec = resolve_spec("720p30", {"target_mb": 25})
    cmd = build_ffmpeg_command("in.mp4", "out.mp4", spec, info, False)
    joined = " ".join(cmd)
    assert "-b:v" in joined
    assert "-crf" not in joined


def test_describe_spec_short():
    assert describe_spec(resolve_spec("无损")) == "无损"
    assert "720p" in describe_spec(resolve_spec("720p30"))


class _Raw:
    pass


class _GroupMessage(_Raw):
    pass


def _event(
    platform: str,
    raw: _Raw,
    *,
    group_id: str = "",
    private: bool = False,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        message_obj=types.SimpleNamespace(raw_message=raw),
        get_platform_name=lambda: platform,
        get_group_id=lambda: group_id,
        is_private_chat=lambda: private,
    )


def test_platform_profiles():
    qq_group = resolve_platform(_event("qq_official", _GroupMessage(), group_id="g"), {})
    assert qq_group.key == "qq_official"
    assert qq_group.supports_reaction is False
    assert qq_group.supports_file is True
    assert qq_group.video_soft_limit_mb == 30
    assert qq_group.passive_reply_budget == 5

    onebot_group = resolve_platform(_event("aiocqhttp", _Raw(), group_id="1"), {})
    assert onebot_group.key == "onebot"
    assert onebot_group.supports_reaction is True
    assert onebot_group.video_soft_limit_mb is None

    forced = resolve_platform(
        _event("qq_official", _GroupMessage(), group_id="g"),
        {"mode": "OneBot"},
    )
    assert forced.key == "onebot"
