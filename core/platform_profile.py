"""平台能力识别。

AstrBot 可能同时接入 OneBot v11（``aiocqhttp``）和 QQ 官方机器人
（``qq_official`` / ``qq_official_webhook``）。两者在贴表情、视频大小限制、
被动回复额度等能力上并不一致，这里把差异集中成一个轻量的能力表。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_PLATFORM_ALIASES = {
    "aiocqhttp": "onebot",
    "onebot": "onebot",
    "onebot_v11": "onebot",
    "onebot11": "onebot",
    "qq_official": "qq_official",
    "qq_official_webhook": "qq_official",
}

_DISPLAY_NAMES = {
    "onebot": "OneBot v11",
    "qq_official": "QQ 官方机器人",
    "generic": "通用平台",
}


@dataclass(frozen=True)
class PlatformProfile:
    """当前事件所属平台的能力快照。"""

    key: str
    name: str
    scene: str
    supports_reaction: bool
    supports_video: bool
    supports_file: bool
    video_soft_limit_mb: int | None
    video_hard_limit_mb: int | None
    passive_reply_budget: int | None

    @property
    def display_name(self) -> str:
        return _DISPLAY_NAMES.get(self.key, self.name or "未知平台")


def normalize_platform_mode(value: Any) -> str:
    """把配置项统一成 ``auto`` / ``onebot`` / ``qq_official``。"""
    text = str(value or "auto").strip().casefold()
    if text in {"", "自动", "auto"}:
        return "auto"
    if text in {"onebot", "onebot v11", "onebot11", "aiocqhttp", "onebot_v11"}:
        return "onebot"
    if text in {
        "qq 官方",
        "qq官方",
        "qq_official",
        "qq official",
        "官方",
        "qq_official_webhook",
    }:
        return "qq_official"
    return "auto"


def normalize_emoji_mode(value: Any) -> str:
    """把表情开关统一成 ``auto`` / ``on`` / ``off``。"""
    text = str(value or "auto").strip().casefold()
    if text in {"", "自动", "auto"}:
        return "auto"
    if text in {"开启", "开", "on", "true", "yes", "1"}:
        return "on"
    if text in {"关闭", "关", "off", "false", "no", "0"}:
        return "off"
    return "auto"


def _scene(event: Any) -> str:
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    raw_name = type(raw).__name__ if raw is not None else ""
    if raw_name == "GroupMessage":
        return "group"
    if raw_name == "C2CMessage":
        return "c2c"
    if raw_name == "Message":
        return "guild"
    if raw_name == "DirectMessage":
        return "guild_dm"

    try:
        group_id = event.get_group_id()
    except Exception:
        group_id = ""
    if group_id:
        return "group"

    try:
        if event.is_private_chat():
            return "c2c"
    except Exception:
        pass
    return "other"


def resolve_platform(event: Any, platform_config: dict | None = None) -> PlatformProfile:
    """根据事件和配置生成平台能力快照。

    Args:
        event: AstrBot 消息事件。
        platform_config: ``_conf_schema.json`` 中的 ``platform`` 配置段。

    Returns:
        当前事件对应的平台能力。
    """
    config = platform_config or {}
    name = str(getattr(event, "get_platform_name", lambda: "")() or "")
    key = _PLATFORM_ALIASES.get(name, "generic")

    forced = normalize_platform_mode(config.get("mode", "auto"))
    if forced != "auto":
        key = forced

    scene = _scene(event)

    soft_raw = config.get("qq_official_video_soft_limit_mb", 30)
    hard_raw = config.get("qq_official_video_hard_limit_mb", 200)
    try:
        soft_limit = int(soft_raw) if soft_raw else None
    except (TypeError, ValueError):
        soft_limit = 30
    try:
        hard_limit = int(hard_raw) if hard_raw else None
    except (TypeError, ValueError):
        hard_limit = 200
    if soft_limit is not None and soft_limit <= 0:
        soft_limit = None
    if hard_limit is not None and hard_limit <= 0:
        hard_limit = None

    if key == "onebot":
        return PlatformProfile(
            key="onebot",
            name=name or "aiocqhttp",
            scene=scene,
            supports_reaction=True,
            supports_video=True,
            supports_file=True,
            video_soft_limit_mb=None,
            video_hard_limit_mb=None,
            passive_reply_budget=None,
        )

    if key == "qq_official":
        return PlatformProfile(
            key="qq_official",
            name=name or "qq_official",
            scene=scene,
            supports_reaction=False,
            supports_video=True,
            supports_file=scene in {"group", "c2c"},
            video_soft_limit_mb=soft_limit,
            video_hard_limit_mb=hard_limit,
            passive_reply_budget=5 if scene == "group" else 4 if scene == "c2c" else None,
        )

    return PlatformProfile(
        key="generic",
        name=name or "generic",
        scene=scene,
        supports_reaction=False,
        supports_video=True,
        supports_file=True,
        video_soft_limit_mb=None,
        video_hard_limit_mb=None,
        passive_reply_budget=None,
    )
