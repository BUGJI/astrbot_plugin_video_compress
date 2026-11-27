"""帮助、状态和高级参数文案。"""

from __future__ import annotations

from typing import Any

from .commands import describe_overrides, preset_table
from .platform_profile import PlatformProfile
from .presets import CompressionSpec, describe_spec

_SCENE_NAMES = {
    "group": "群聊",
    "c2c": "单聊",
    "guild": "频道",
    "guild_dm": "频道私信",
    "other": "其他",
}


def build_help_text(profile: PlatformProfile, personal: dict[str, Any]) -> str:
    lines = [
        "【视频压缩】",
        "发送视频后直接发送 /压缩视频；也可以回复一条视频再发送命令。",
        "",
        "简易预设：",
        preset_table(),
        "· 25MB：按目标大小压缩（QQ 官方推荐）",
        "",
        "示例：",
        "· /压缩视频 720p30",
        "· /压缩视频 25MB",
        "· /压缩视频 无损",
        "",
        "个人默认（仅当前群/会话生效）：",
        "· /压缩视频 默认 720p30",
        "· /压缩视频 默认 25MB",
        "· /压缩视频 默认 清除",
        "",
        "高级参数：",
        "· /压缩视频 高级",
        "· /压缩视频 设置 crf 22",
        "· /压缩视频 设置 max_height 1080 fps 60",
        "",
        "查看状态：/压缩视频 状态",
    ]

    if personal:
        lines += ["", f"当前个人默认：{describe_overrides(personal)}"]

    if profile.key == "qq_official":
        soft = profile.video_soft_limit_mb
        limit_text = f"{soft}MB" if soft else "平台限制"
        lines += [
            "",
            "QQ 官方提示：",
            "· 不支持贴表情，处理进度以文字提示",
            f"· 视频软限制约 {limit_text}，超过后会按配置重新压缩或转为文件",
            "· 单条消息的被动回复次数有限，自动压缩可能排队",
        ]
    elif profile.key == "onebot":
        lines += [
            "",
            "OneBot 提示：",
            "· 贴表情取决于协议端是否实现 set_msg_emoji_like，失败会自动忽略",
        ]

    if profile.scene == "guild":
        lines += [
            "",
            "频道提示：",
            "· 频道场景不支持文件消息，超过视频限制时只能重新压缩或报错",
        ]

    return "\n".join(lines)


def build_advanced_text(personal: dict[str, Any]) -> str:
    lines = [
        "【高级压缩参数】",
        "设置：/压缩视频 设置 <参数> <值>",
        "清除单个：/压缩视频 设置 清除 <参数>",
        "清除全部：/压缩视频 设置 清除",
        "",
        "· quality <预设>：切换预设，例如 720p30、480p30、无损",
        "· target_mb <大小>：按目标大小压缩，例如 25MB",
        "· max_height <高度>：1080 / 720 / 480 / 360 / source",
        "· fps <帧率>：60 / 30 / 24 / source",
        "· crf <0-51>：越小越清晰、文件越大；默认 23",
        "· audio_kbps <码率>：0 / 64 / 96 / 128 / 192；0 表示静音",
        "· preset <编码预设>：ultrafast / fast / medium / slow / veryslow",
        "· keep_audio <开/关>：是否保留音频",
        "",
        "示例：",
        "· /压缩视频 设置 crf 22",
        "· /压缩视频 设置 max_height 1080 fps 60",
        "· /压缩视频 设置 target_mb 25MB",
        "· /压缩视频 设置 audio_kbps 0",
        "",
        f"当前个人设置：{describe_overrides(personal)}",
    ]
    return "\n".join(lines)


def build_status_text(
    profile: PlatformProfile,
    effective: CompressionSpec,
    personal: dict[str, Any],
    scope_id: str,
) -> str:
    reaction = "✅" if profile.supports_reaction else "❌"
    video = "✅" if profile.supports_video else "❌"
    file_support = "✅" if profile.supports_file else "❌"

    if profile.video_soft_limit_mb:
        limit = f" | 视频软限制 {profile.video_soft_limit_mb}MB"
    elif profile.video_hard_limit_mb:
        limit = f" | 视频硬限制 {profile.video_hard_limit_mb}MB"
    else:
        limit = ""

    budget = (
        f" | 被动回复 {profile.passive_reply_budget} 次/条"
        if profile.passive_reply_budget
        else ""
    )

    lines = [
        "【视频压缩状态】",
        f"平台：{profile.display_name}（{profile.name}）",
        f"场景：{_SCENE_NAMES.get(profile.scene, profile.scene)}",
        f"能力：贴表情 {reaction} | 视频 {video} | 文件 {file_support}{limit}{budget}",
        f"会话 ID：{scope_id or '未知'}",
        f"当前生效：{describe_spec(effective)}",
        f"个人默认：{describe_overrides(personal)}",
        "",
        "简易入口：/压缩视频 720p30 或 /压缩视频 25MB",
        "高级入口：/压缩视频 高级",
    ]
    return "\n".join(lines)
