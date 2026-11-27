"""``/压缩视频`` 的参数解析与展示辅助。"""

from __future__ import annotations

import re
from typing import Any

from .presets import PRESETS, match_preset, preset_label

HELP_WORDS = {"帮助", "help", "?", "？", "用法", "说明"}
STATUS_WORDS = {"状态", "查看", "status", "参数", "当前"}
ADVANCED_WORDS = {"高级", "advanced", "更多", "自定义", "详细"}
DEFAULT_WORDS = {"默认", "default"}
SET_WORDS = {"设置", "set", "设定"}
CLEAR_WORDS = {"清除", "重置", "清空", "删除", "reset", "clear"}

ADVANCED_FIELDS = (
    "quality",
    "target_mb",
    "max_height",
    "fps",
    "crf",
    "audio_kbps",
    "preset",
    "keep_audio",
)

FIELD_ALIASES = {
    "quality": "quality",
    "预设": "quality",
    "画质": "quality",
    "target": "target_mb",
    "target_mb": "target_mb",
    "targetmb": "target_mb",
    "size": "target_mb",
    "大小": "target_mb",
    "目标": "target_mb",
    "目标大小": "target_mb",
    "max_height": "max_height",
    "maxheight": "max_height",
    "height": "max_height",
    "resolution": "max_height",
    "分辨率": "max_height",
    "高度": "max_height",
    "fps": "fps",
    "帧率": "fps",
    "crf": "crf",
    "质量": "crf",
    "audio": "audio_kbps",
    "audio_kbps": "audio_kbps",
    "audiokbps": "audio_kbps",
    "audio_bitrate": "audio_kbps",
    "bitrate": "audio_kbps",
    "音频": "audio_kbps",
    "音质": "audio_kbps",
    "preset": "preset",
    "编码预设": "preset",
    "keep_audio": "keep_audio",
    "keepaudio": "keep_audio",
    "保留音频": "keep_audio",
    "音频开关": "keep_audio",
}

FIELD_LABELS = {
    "quality": "预设",
    "target_mb": "目标大小",
    "max_height": "分辨率",
    "fps": "帧率",
    "crf": "CRF",
    "audio_kbps": "音频码率",
    "preset": "编码预设",
    "keep_audio": "保留音频",
}

_FFMPEG_PRESETS = {
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
}


def normalize_field(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "")).casefold()


def parse_target_mb(value: str) -> float | None:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:m|mb|mib|兆)?", text, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    if 1 <= number <= 2000:
        return number
    return None


def _parse_bool(value: str) -> bool | None:
    text = str(value or "").strip().casefold()
    if text in {"开", "开启", "on", "true", "yes", "1", "是"}:
        return True
    if text in {"关", "关闭", "off", "false", "no", "0", "否"}:
        return False
    return None


def coerce_field(field: str, value: str) -> tuple[Any, str | None]:
    """把字段值转换成配置里保存的类型。"""
    raw = str(value or "").strip()

    if field == "quality":
        key = match_preset(raw)
        if key is None:
            return None, f"未知预设：{raw}"
        return key, None

    if field == "target_mb":
        number = parse_target_mb(raw)
        if number is None:
            return None, "目标大小需要是 1~2000 之间的数字，例如 25MB"
        return number, None

    if field == "max_height":
        if raw.casefold() in {"source", "原始", "原画", "原分辨率", "0", "auto"}:
            return 0, None
        match = re.fullmatch(r"(\d{3,4})\s*p?", raw, re.IGNORECASE)
        if not match:
            return None, "分辨率需要是 1080p/720p/480p/360p 或 source"
        height = int(match.group(1))
        if not 144 <= height <= 4320:
            return None, "分辨率需要在 144~4320 之间"
        return height, None

    if field == "fps":
        if raw.casefold() in {"source", "原始", "原帧率", "0", "auto"}:
            return 0, None
        match = re.fullmatch(r"(\d{1,3})\s*(?:fps)?", raw, re.IGNORECASE)
        if not match:
            return None, "帧率需要是 60/30/24 或 source"
        fps = int(match.group(1))
        if not 1 <= fps <= 120:
            return None, "帧率需要在 1~120 之间"
        return fps, None

    if field == "crf":
        match = re.fullmatch(r"\d{1,2}", raw)
        if not match:
            return None, "CRF 需要是 0~51 之间的整数"
        crf = int(raw)
        if not 0 <= crf <= 51:
            return None, "CRF 需要在 0~51 之间"
        return crf, None

    if field == "audio_kbps":
        if raw.casefold() in {"静音", "关闭", "关", "off", "none", "0"}:
            return 0, None
        match = re.fullmatch(r"(\d{1,4})\s*(?:k|kbps)?", raw, re.IGNORECASE)
        if not match:
            return None, "音频码率需要是数字（kbps），0 表示静音"
        kbps = int(match.group(1))
        if not 0 <= kbps <= 512:
            return None, "音频码率需要在 0~512 之间"
        return kbps, None

    if field == "preset":
        text = raw.casefold()
        if text not in _FFMPEG_PRESETS:
            return None, "编码预设可选：" + " / ".join(sorted(_FFMPEG_PRESETS))
        return text, None

    if field == "keep_audio":
        parsed = _parse_bool(raw)
        if parsed is None:
            return None, "保留音频需要是 开/关"
        return parsed, None

    return None, f"未知参数：{field}"


def parse_override_text(text: str) -> tuple[dict[str, Any], str | None]:
    """解析一次性的覆盖参数。

    支持：
    - ``720p30`` / ``有损压缩 720p 30``
    - ``25MB``
    - ``720p30 crf 22``
    - ``crf 22 max_height 1080``
    - ``crf=22 preset=slow``
    """
    raw = str(text or "").strip()
    if not raw:
        return {}, None

    preset = match_preset(raw)
    if preset is not None:
        return {"quality": preset}, None

    target = parse_target_mb(raw)
    if target is not None:
        return {"target_mb": target}, None

    tokens = raw.split()
    overrides: dict[str, Any] = {}
    index = 0

    # 允许 ``quality 有损压缩 720p 30`` 这种带空格的预设值。
    if tokens and normalize_field(tokens[0]) in {"quality", "预设", "画质"}:
        preset = match_preset(" ".join(tokens[1:]))
        if preset is not None:
            return {"quality": preset}, None

    # 先从左到右尝试最长的预设前缀，支持“有损压缩 720p 30 25MB”。
    first_preset = None
    for end in range(len(tokens), 0, -1):
        candidate = match_preset(" ".join(tokens[:end]))
        if candidate is not None:
            first_preset = candidate
            index = end
            break

    if first_preset is not None:
        overrides["quality"] = first_preset
    else:
        first_target = parse_target_mb(tokens[0])
        if first_target is not None:
            overrides["target_mb"] = first_target
            index = 1

    while index < len(tokens):
        token = tokens[index]

        # 允许在参数序列里再出现一个独立预设或目标大小，
        # 例如 ``720p30 25MB`` / ``25MB crf 22``。
        if "=" not in token:
            standalone_preset = match_preset(token)
            if standalone_preset is not None:
                overrides["quality"] = standalone_preset
                index += 1
                continue
            standalone_target = parse_target_mb(token)
            if standalone_target is not None:
                overrides["target_mb"] = standalone_target
                index += 1
                continue

        if "=" in token:
            key, value = token.split("=", 1)
            index += 1
        else:
            if index + 1 >= len(tokens):
                return {}, f"参数 {token} 缺少值"
            key = token
            value = tokens[index + 1]
            index += 2

        field = FIELD_ALIASES.get(normalize_field(key))
        if field is None:
            return {}, f"未知参数：{key}"
        converted, error = coerce_field(field, value)
        if error:
            return {}, error
        overrides[field] = converted

    if not overrides:
        return {}, "没有识别到有效参数"
    return overrides, None


def with_quality_reset(
    current: dict[str, Any], changes: dict[str, Any]
) -> dict[str, Any]:
    """设置预设时清掉同层高级参数，避免“看起来是预设、实际被覆盖”。"""
    result = dict(current)
    if "quality" not in changes:
        result.update(changes)
        return result

    # 先清掉旧的高级参数，再应用本次命令里的高级参数，
    # 这样 ``默认 720p30 crf 22`` 仍然能同时生效。
    for field in ADVANCED_FIELDS:
        if field != "quality":
            result.pop(field, None)
    result["quality"] = changes["quality"]
    for key, value in changes.items():
        if key != "quality":
            result[key] = value
    return result


def describe_overrides(data: dict[str, Any]) -> str:
    if not data:
        return "未设置"

    parts: list[str] = []
    quality = data.get("quality")
    if quality:
        parts.append(f"预设 {preset_label(str(quality))}")

    if data.get("target_mb"):
        parts.append(f"目标 {float(data['target_mb']):g}MB")

    if "max_height" in data:
        height = int(data.get("max_height") or 0)
        parts.append("原始分辨率" if height == 0 else f"{height}p")

    if "fps" in data:
        fps = int(data.get("fps") or 0)
        parts.append("原始帧率" if fps == 0 else f"{fps}fps")

    if "crf" in data:
        parts.append(f"CRF {data['crf']}")

    if "audio_kbps" in data:
        kbps = int(data.get("audio_kbps") or 0)
        parts.append("静音" if kbps == 0 else f"音频 {kbps}kbps")
    elif "keep_audio" in data:
        parts.append("保留音频" if data["keep_audio"] else "静音")

    if data.get("preset"):
        parts.append(f"编码预设 {data['preset']}")

    return " · ".join(parts) if parts else "未设置"


def preset_table() -> str:
    """简易预设列表，帮助文本和高级文本共用。"""
    lines = []
    for preset in PRESETS.values():
        key = "无损" if preset.key == "lossless" else preset.key
        lines.append(f"· {key}：{preset.label}")
    return "\n".join(lines)
