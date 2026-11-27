"""压缩预设、用户参数合并与 ffmpeg 命令构造。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CompressionSpec:
    """一次压缩使用的具体参数。"""

    lossless: bool = False
    max_height: int | None = 720
    fps: int | None = 30
    crf: int = 23
    audio_kbps: int | None = 128
    preset: str = "medium"
    keep_audio: bool = True
    target_mb: float | None = None


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    spec: CompressionSpec


PRESETS: dict[str, Preset] = {
    "lossless": Preset(
        "lossless",
        "无损压缩",
        CompressionSpec(
            lossless=True,
            max_height=None,
            fps=None,
            crf=0,
            audio_kbps=192,
            preset="veryslow",
        ),
    ),
    "720p60": Preset(
        "720p60",
        "有损压缩 720p 60",
        CompressionSpec(max_height=720, fps=60, crf=23, audio_kbps=128),
    ),
    "720p30": Preset(
        "720p30",
        "有损压缩 720p 30",
        CompressionSpec(max_height=720, fps=30, crf=23, audio_kbps=128),
    ),
    "480p60": Preset(
        "480p60",
        "有损压缩 480p 60",
        CompressionSpec(max_height=480, fps=60, crf=25, audio_kbps=96),
    ),
    "480p30": Preset(
        "480p30",
        "有损压缩 480p 30",
        CompressionSpec(max_height=480, fps=30, crf=26, audio_kbps=64),
    ),
    "360p30": Preset(
        "360p30",
        "有损压缩 360p 30",
        CompressionSpec(max_height=360, fps=30, crf=28, audio_kbps=48),
    ),
}

DEFAULT_SPEC = PRESETS["720p30"].spec

_ALIASES: dict[str, str] = {}


def _register(key: str, *aliases: str) -> None:
    for alias in aliases:
        _ALIASES[normalize_text(alias)] = key


def normalize_text(value: str | None) -> str:
    """去掉空白、下划线、连字符和斜杠并转小写，便于匹配别名。"""
    return re.sub(r"[\s_\-/]+", "", str(value or "")).casefold()


def _register_presets() -> None:
    _register(
        "lossless",
        "无损压缩",
        "无损",
        "原画",
        "原画质",
        "lossless",
    )
    _register(
        "720p60",
        "有损压缩 720p 60",
        "720p60",
        "720p_60",
        "720p-60",
        "高清60",
        "hd60",
    )
    _register(
        "720p30",
        "有损压缩 720p 30",
        "720p30",
        "720p_30",
        "720p",
        "高清",
        "hd",
    )
    _register(
        "480p60",
        "有损压缩 480p 60",
        "480p60",
        "480p_60",
        "标清60",
    )
    _register(
        "480p30",
        "有损压缩 480p 30",
        "480p30",
        "480p_30",
        "480p",
        "标清",
    )
    _register(
        "360p30",
        "有损压缩 360p 30",
        "360p30",
        "360p_30",
        "360p",
        "流畅",
    )


_register_presets()


def match_preset(value: str | None) -> str | None:
    """把用户输入/全局配置转换成预设 key。"""
    return _ALIASES.get(normalize_text(value))


def preset_label(key: str | None) -> str:
    preset = PRESETS.get(str(key or ""))
    return preset.label if preset else str(key or "")


def spec_from_preset(value: str | None) -> CompressionSpec | None:
    key = match_preset(value)
    if key is None:
        return None
    return PRESETS[key].spec


def resolve_spec(
    global_quality: str | None,
    personal: Mapping[str, Any] | None = None,
    one_off: Mapping[str, Any] | None = None,
) -> CompressionSpec:
    """按“全局预设 -> 个人默认 -> 本次参数”的顺序合并压缩参数。"""
    spec = spec_from_preset(global_quality) or DEFAULT_SPEC
    if personal:
        spec = apply_layer(spec, personal)
    if one_off:
        spec = apply_layer(spec, one_off)
    return spec


def apply_layer(spec: CompressionSpec, layer: Mapping[str, Any]) -> CompressionSpec:
    """把一层覆盖参数应用到基础 spec 上。

    层里出现 ``quality`` 时先切换成该预设，再应用同层的其他高级参数。
    """
    data = asdict(spec)

    quality = layer.get("quality")
    if quality:
        preset = spec_from_preset(str(quality))
        if preset is not None:
            data = asdict(preset)

    if "lossless" in layer:
        data["lossless"] = bool(layer["lossless"])
    if "max_height" in layer:
        value = _to_int(layer["max_height"])
        data["max_height"] = None if not value else value
    if "fps" in layer:
        value = _to_int(layer["fps"])
        data["fps"] = None if not value else value
    if "crf" in layer:
        data["crf"] = max(0, min(51, _to_int(layer["crf"]) or 0))
    if "audio_kbps" in layer:
        value = _to_int(layer["audio_kbps"])
        data["audio_kbps"] = None if value == 0 else value
        # audio_kbps=0 与“静音”等价，避免出现 keep_audio=True 但没有码率
        data["keep_audio"] = value != 0
    if "preset" in layer and str(layer["preset"] or "").strip():
        data["preset"] = str(layer["preset"]).strip()
    if "keep_audio" in layer:
        data["keep_audio"] = bool(layer["keep_audio"])
    if "target_mb" in layer:
        value = _to_float(layer["target_mb"])
        data["target_mb"] = None if not value else value
        if value:
            # 目标大小必须依赖有损编码；避免出现“无损 + 25MB”这种矛盾组合
            data["lossless"] = False

    return CompressionSpec(**data)


def describe_spec(spec: CompressionSpec) -> str:
    if spec.lossless:
        text = "无损"
    else:
        parts: list[str] = []
        if spec.max_height:
            parts.append(f"{spec.max_height}p")
        if spec.fps:
            parts.append(f"{spec.fps}fps")
        if spec.target_mb:
            parts.append(f"目标 {_fmt_number(spec.target_mb)}MB")
        else:
            parts.append(f"CRF {spec.crf}")
        if not spec.keep_audio:
            parts.append("静音")
        text = " · ".join(parts)
    if spec.lossless and not spec.keep_audio:
        text = f"{text} · 静音"
    return text


def _fmt_number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _even(value: float) -> int:
    return max(2, int(round(value / 2.0)) * 2)


def build_ffmpeg_command(
    input_path: str,
    output_path: str,
    spec: CompressionSpec,
    info: Mapping[str, Any],
    use_nvenc: bool,
) -> list[str]:
    """构造 ffmpeg 压缩命令。

    Args:
        input_path: 输入视频路径。
        output_path: 输出 mp4 路径。
        spec: 压缩参数。
        info: ffprobe 结果，包含 width/height/fps/duration。
        use_nvenc: 是否使用 NVIDIA NVENC。

    Returns:
        可直接交给 ``asyncio.create_subprocess_exec`` 的参数列表。
    """
    use_nvenc = bool(use_nvenc and not spec.lossless)
    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
    ]

    if use_nvenc:
        cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]

    cmd += [
        "-i",
        input_path,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    ]

    filters: list[str] = []
    # 用一个 16:9 的“最大画框”并保持原始宽高比，既不会拉伸，
    # 也能正确处理竖屏/带旋转元数据的手机视频。
    source_height = _to_int(info.get("height"))
    if not spec.lossless and spec.max_height:
        target_height = int(spec.max_height)
        box_width = _even(target_height * 16 / 9)
        if source_height and source_height <= target_height:
            pass
        elif use_nvenc:
            filters.append(
                f"scale_cuda=w={box_width}:h={target_height}:"
                "force_original_aspect_ratio=decrease:force_divisible_by=2"
            )
        else:
            filters.append(
                f"scale=w={box_width}:h={target_height}:"
                "force_original_aspect_ratio=decrease:force_divisible_by=2"
            )

    if filters:
        cmd += ["-vf", ",".join(filters)]

    source_fps = float(info.get("fps") or 0)
    if spec.fps and (not source_fps or source_fps > float(spec.fps) + 0.01):
        cmd += ["-r", str(int(spec.fps))]

    duration = float(info.get("duration") or 0)
    if spec.lossless:
        cmd += [
            "-c:v",
            "libx264",
            "-crf",
            "0",
            "-preset",
            "veryslow",
            "-pix_fmt",
            "yuv420p",
        ]
    elif spec.target_mb and duration > 0:
        audio_kbps = int(spec.audio_kbps or 128) if spec.keep_audio else 0
        total_kbps = float(spec.target_mb) * 8192.0 / duration
        video_kbps = max(100.0, min(50000.0, total_kbps - audio_kbps))
        maxrate = int(video_kbps * 1.15)
        bufsize = int(video_kbps * 2)
        if use_nvenc:
            cmd += [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-rc",
                "vbr",
                "-b:v",
                f"{int(video_kbps)}k",
                "-maxrate",
                f"{maxrate}k",
                "-bufsize",
                f"{bufsize}k",
            ]
        else:
            cmd += [
                "-c:v",
                "libx264",
                "-preset",
                spec.preset,
                "-profile:v",
                "high",
                "-b:v",
                f"{int(video_kbps)}k",
                "-maxrate",
                f"{maxrate}k",
                "-bufsize",
                f"{bufsize}k",
                "-pix_fmt",
                "yuv420p",
            ]
    else:
        if use_nvenc:
            cmd += [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-rc",
                "vbr",
                "-cq",
                str(int(spec.crf)),
            ]
        else:
            cmd += [
                "-c:v",
                "libx264",
                "-preset",
                spec.preset,
                "-profile:v",
                "high",
                "-crf",
                str(int(spec.crf)),
                "-pix_fmt",
                "yuv420p",
            ]

    if spec.keep_audio and spec.lossless:
        # 真正的“无损”预设保留原始音频，避免二次有损编码
        cmd += ["-c:a", "copy"]
    elif spec.keep_audio:
        cmd += ["-c:a", "aac", "-b:a", f"{int(spec.audio_kbps or 128)}k", "-ac", "2"]
    else:
        cmd += ["-an"]

    cmd += [
        "-movflags",
        "+faststart",
        "-metadata:s:v",
        "rotate=0",
        output_path,
    ]
    return cmd
