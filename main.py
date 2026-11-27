import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Optional, Tuple

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import File, Plain, Reply, Video
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from .core.commands import (
    ADVANCED_WORDS,
    CLEAR_WORDS,
    DEFAULT_WORDS,
    FIELD_ALIASES,
    HELP_WORDS,
    SET_WORDS,
    STATUS_WORDS,
    describe_overrides,
    normalize_field,
    parse_override_text,
    with_quality_reset,
)
from .core.platform_profile import (
    PlatformProfile,
    normalize_emoji_mode,
    resolve_platform,
)
from .core.preferences import PreferenceStore
from .core.presets import (
    CompressionSpec,
    build_ffmpeg_command,
    describe_spec,
    resolve_spec,
)
from .core.texts import build_advanced_text, build_help_text, build_status_text

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".flv",
    ".webm",
    ".m4v",
    ".3gp",
    ".ts",
    ".mts",
}


@dataclass
class CompressionResult:
    path: str | None = None
    size_mb: float = 0.0
    used_gpu: bool = False
    file_fallback: bool = False
    error: str | None = None


@register(
    "astrbot_plugin_video_compress",
    "BUGJI",
    "视频自动压缩器 - 群内视频自动压缩并发回原群 (支持 NVIDIA GPU 加速与 OneBot/QQ 官方平台)",
    "2.1.0",
    "https://github.com/BUGJI/astrbot_plugin_video_compress",
)
class VideoCompressPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context, config)
        self.config = config or {}
        self.video_config = self.config.get("video_compress", {}) or {}
        self.group_config = self.config.get("group_control", {}) or {}
        self.platform_config = self.config.get("platform", {}) or {}
        self.oversize_config = self.config.get("oversize", {}) or {}

        self._gpu_available: bool | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._processing: set[str] = set()
        self.preferences = PreferenceStore(self)

    async def initialize(self):
        logger.info("视频压缩插件已加载 (支持 NVIDIA GPU 加速)")
        if not await self._check_ffmpeg():
            logger.warning("未检测到 ffmpeg/ffprobe，视频压缩功能将不可用")

        self._gpu_available = await self._check_nvenc_support()
        if self._gpu_available:
            logger.info("检测到 NVIDIA GPU，将使用 NVENC 硬件加速")
        else:
            logger.info("未检测到 NVIDIA GPU 或 NVENC 不支持，将使用 CPU 软编码")

        if str(self.video_config.get("use_gpu", "auto")).lower() == "enabled":
            if not self._gpu_available:
                logger.warning("配置要求启用 GPU，但当前环境不可用，将回退 CPU")

        self._semaphore = asyncio.Semaphore(self._max_concurrent())

        if str(self.group_config.get("mode", "白名单")) in {"白名单", "whitelist"}:
            if not (self.group_config.get("group_ids") or []):
                logger.warning(
                    "群组模式为白名单但群号列表为空，自动压缩不会在任何群生效；"
                    "可在 WebUI 配置，或发送 /压缩视频 状态 查看当前会话 ID"
                )

    async def terminate(self):
        self._processing.clear()

    # ---------------- 平台与能力 ----------------

    def _profile(self, event: AstrMessageEvent) -> PlatformProfile:
        return resolve_platform(event, self.platform_config)

    def _emoji_allowed(self, profile: PlatformProfile) -> bool:
        mode = normalize_emoji_mode(self.platform_config.get("emoji", "auto"))
        if mode == "off":
            return False
        if mode == "on":
            return True
        return profile.supports_reaction

    def _progress_allowed(self, manual: bool) -> bool:
        mode = str(self.video_config.get("progress_message", "自动")).strip().casefold()
        if mode in {"关闭", "关", "off", "false", "0"}:
            return False
        if mode in {"总是", "开启", "开", "on", "true", "1"}:
            return True
        return manual

    def _max_concurrent(self) -> int:
        try:
            value = int(self.video_config.get("max_concurrent", 1))
        except (TypeError, ValueError):
            value = 1
        return max(1, min(8, value))

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent())
        return self._semaphore

    # ---------------- 基础工具 ----------------

    async def _check_ffmpeg(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except (FileNotFoundError, OSError):
            return False

    async def _check_nvenc_support(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0:
                return False

            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-encoders",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return "h264_nvenc" in stdout.decode("utf-8", "ignore")
        except (FileNotFoundError, OSError):
            return False

    def _should_use_gpu(self) -> bool:
        value = str(self.video_config.get("use_gpu", "auto")).strip().casefold()
        if value in {"auto", "自动"}:
            return bool(self._gpu_available)
        if value in {"enabled", "开启", "开", "on", "true"}:
            return True
        if value in {"disabled", "关闭", "关", "off", "false"}:
            return False
        return bool(self._gpu_available)

    async def _get_video_info(self, file_path: str) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,avg_frame_rate,r_frame_rate,duration,"
                "side_data_list:stream_tags=rotate:format=duration",
                "-of",
                "json",
                file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0 or not stdout:
                logger.debug(
                    "ffprobe 失败: %s", stderr.decode("utf-8", "ignore")[-500:]
                )
                return {}

            payload = json.loads(stdout.decode("utf-8", "ignore"))
            streams = payload.get("streams") or []
            if not streams:
                return {}
            stream = streams[0]
            duration = self._to_float(stream.get("duration"))
            if not duration:
                duration = self._to_float((payload.get("format") or {}).get("duration"))

            width = self._to_int(stream.get("width"))
            height = self._to_int(stream.get("height"))
            rotation = self._video_rotation(stream)
            if rotation % 180 == 90:
                width, height = height, width

            return {
                "width": width,
                "height": height,
                "fps": self._parse_fraction(
                    stream.get("avg_frame_rate") or stream.get("r_frame_rate")
                ),
                "duration": duration,
            }
        except Exception as e:
            logger.debug(f"获取视频信息失败: {e}")
            return {}

    @staticmethod
    def _to_int(value) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_fraction(value) -> float:
        text = str(value or "").strip()
        if not text:
            return 0.0
        try:
            if "/" in text:
                numerator, denominator = text.split("/", 1)
                denominator_value = int(denominator)
                if denominator_value == 0:
                    return 0.0
                return float(Fraction(int(numerator), denominator_value))
            return float(text)
        except (ValueError, ZeroDivisionError):
            return 0.0

    @staticmethod
    def _video_rotation(stream: dict) -> int:
        """读取 ffprobe 的旋转元数据，返回 0/90/180/270。"""
        values = []
        for item in stream.get("side_data_list") or []:
            if isinstance(item, dict) and item.get("rotation") is not None:
                values.append(item.get("rotation"))
        tags = stream.get("tags")
        if isinstance(tags, dict) and tags.get("rotate") is not None:
            values.append(tags.get("rotate"))

        for value in values:
            try:
                rotation = abs(int(float(value))) % 360
            except (TypeError, ValueError):
                continue
            if rotation in {90, 180, 270}:
                return rotation
        return 0

    # ---------------- 消息提取 ----------------

    def _check_group_allowed(self, group_id: str) -> bool:
        mode = str(self.group_config.get("mode", "白名单")).strip()
        raw_ids = self.group_config.get("group_ids") or []
        if isinstance(raw_ids, str):
            raw_ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
        group_ids = {str(item) for item in raw_ids}
        if mode in {"全部", "all", "*"}:
            return True
        if mode in {"黑名单", "blacklist"}:
            return group_id not in group_ids
        return group_id in group_ids

    def _extract_video(self, messages: list) -> Video | File | None:
        for msg in messages:
            if isinstance(msg, Video):
                return msg
            if isinstance(msg, File) and self._is_video_file(msg):
                return msg
            if isinstance(msg, Reply) and msg.chain:
                for comp in msg.chain:
                    if isinstance(comp, Video):
                        return comp
                    if isinstance(comp, File) and self._is_video_file(comp):
                        return comp
        return None

    @staticmethod
    def _is_video_file(file_component: File) -> bool:
        candidates = (
            getattr(file_component, "name", None),
            getattr(file_component, "file_", None),
            getattr(file_component, "url", None),
        )
        for candidate in candidates:
            if not candidate:
                continue
            path = str(candidate).split("?", 1)[0]
            if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS:
                return True
        return False

    def _extract_reply_message_id(self, messages: list):
        for msg in messages:
            if isinstance(msg, Reply):
                if getattr(msg, "id", None):
                    return msg.id
                if getattr(msg, "message_id", None):
                    return msg.message_id
        return None

    def _extract_video_with_reply(
        self, messages: list
    ) -> Tuple[Optional[Video | File], Optional[int]]:
        reply_message_id = None
        for msg in messages:
            if isinstance(msg, Reply):
                if getattr(msg, "id", None):
                    reply_message_id = msg.id
                elif getattr(msg, "message_id", None):
                    reply_message_id = msg.message_id
                if msg.chain:
                    for comp in msg.chain:
                        if isinstance(comp, Video):
                            return comp, reply_message_id
                        if isinstance(comp, File) and self._is_video_file(comp):
                            return comp, reply_message_id

            if isinstance(msg, Video):
                return msg, None
            if isinstance(msg, File) and self._is_video_file(msg):
                return msg, None

        return None, None

    async def _resolve_video_path(self, video: Video | File) -> str:
        if isinstance(video, Video):
            return await video.convert_to_file_path()
        return await video.get_file()

    async def _mark_emoji(
        self,
        event: AstrMessageEvent,
        profile: PlatformProfile,
        stage: str,
        target_message_id=None,
    ) -> bool:
        if not self._emoji_allowed(profile):
            return False

        bot = getattr(event, "bot", None)
        if bot is None:
            return False
        if profile.key == "onebot" and not hasattr(bot, "set_msg_emoji_like"):
            return False

        message_id = target_message_id
        if not message_id:
            message_id = getattr(
                getattr(event, "message_obj", None), "message_id", None
            )
        try:
            numeric_id = int(message_id)
        except (TypeError, ValueError):
            return False

        if stage == "start":
            emoji_id = self.video_config.get("emoji_processing_id", 289)
            emoji_type = self.video_config.get("emoji_processing_type", "1")
        else:
            emoji_id = self.video_config.get("emoji_done_id", 124)
            emoji_type = self.video_config.get("emoji_done_type", "1")

        try:
            await bot.set_msg_emoji_like(
                message_id=numeric_id,
                emoji_id=str(emoji_id),
                emoji_type=str(emoji_type),
                set=True,
            )
            return True
        except Exception as e:
            logger.debug(f"添加表情失败: {e}")
            return False

    # ---------------- 自动压缩 ----------------

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        profile = self._profile(event)
        if profile.scene == "group":
            if not self.video_config.get("auto_compress", False):
                return
            group_id = event.get_group_id()
            if not group_id or not self._check_group_allowed(group_id):
                return
        elif profile.scene == "c2c":
            if not self.video_config.get("auto_compress_private", False):
                return
        else:
            return

        message_str = (event.get_message_str() or "").strip()
        if message_str.startswith("/") or message_str.startswith(
            ("压缩视频", "视频压缩")
        ):
            return

        messages = event.get_messages() or []
        video = self._extract_video(messages)
        if not video:
            return

        reply_id = self._extract_reply_message_id(messages)
        personal = await self.preferences.get(self._pref_key(event))
        spec = resolve_spec(self.video_config.get("quality"), personal, None)
        async for result in self._process_video(
            event, video, reply_id, spec, manual=False
        ):
            yield result

    # ---------------- 手动压缩 ----------------

    @filter.command("压缩视频", alias={"视频压缩"})
    async def cmd_compress_video(self, event: AstrMessageEvent, quality: str = ""):
        """压缩视频：/压缩视频 [预设|大小|帮助|状态|高级|默认|设置]"""
        del quality  # 兼容旧参数，实际从原始消息尾部解析，支持多词预设
        profile = self._profile(event)
        tail = self._command_tail(event)
        tokens = tail.split()
        keyword = tokens[0].casefold() if tokens else ""
        personal = await self.preferences.get(self._pref_key(event))

        if keyword in HELP_WORDS:
            yield event.plain_result(build_help_text(profile, personal))
            return

        if keyword in STATUS_WORDS:
            effective = resolve_spec(
                self.video_config.get("quality"), personal, None
            )
            yield event.plain_result(
                build_status_text(
                    profile, effective, personal, self._scope_id(event)
                )
            )
            return

        if keyword in ADVANCED_WORDS:
            yield event.plain_result(build_advanced_text(personal))
            return

        if keyword in DEFAULT_WORDS:
            rest = tail[len(tokens[0]) :].strip() if tokens else ""
            text = await self._handle_default(event, personal, rest)
            yield event.plain_result(text)
            return

        if keyword in SET_WORDS:
            rest = tail[len(tokens[0]) :].strip() if tokens else ""
            text = await self._handle_set(event, personal, rest)
            yield event.plain_result(text)
            return

        overrides, error = parse_override_text(tail)
        if error:
            yield event.plain_result(f"{error}\n发送 /压缩视频 帮助 查看用法")
            return

        messages = event.get_messages() or []
        video, reply_id = self._extract_video_with_reply(messages)
        if not video:
            if not tail:
                yield event.plain_result(build_help_text(profile, personal))
            else:
                yield event.plain_result("请发送或回复一个视频后再使用此命令")
            return

        spec = resolve_spec(self.video_config.get("quality"), personal, overrides)
        async for result in self._process_video(
            event, video, reply_id, spec, manual=True
        ):
            yield result

    async def _handle_default(
        self,
        event: AstrMessageEvent,
        personal: dict,
        rest: str,
    ) -> str:
        if not rest:
            return (
                f"当前个人默认：{describe_overrides(personal)}\n"
                "设置：/压缩视频 默认 720p30\n"
                "按大小：/压缩视频 默认 25MB\n"
                "清除：/压缩视频 默认 清除"
            )

        parts = rest.split()
        if parts[0].casefold() in CLEAR_WORDS:
            key = self._pref_key(event)
            if len(parts) == 1:
                await self.preferences.clear(key)
                return "已清除全部个人默认参数"

            field = FIELD_ALIASES.get(normalize_field(parts[1]))
            if field is None:
                return f"未知参数：{parts[1]}"
            updated = dict(personal)
            updated.pop(field, None)
            if field == "audio_kbps":
                updated.pop("keep_audio", None)
            await self.preferences.set(key, updated)
            return f"已清除个人默认中的 {field}"

        changes, error = parse_override_text(rest)
        if error:
            return f"{error}\n发送 /压缩视频 高级 查看可设置项"

        updated = with_quality_reset(personal, changes)
        await self.preferences.set(self._pref_key(event), updated)
        return (
            f"已保存个人默认：{describe_overrides(updated)}\n"
            "仅当前群/会话生效。"
        )

    async def _handle_set(
        self,
        event: AstrMessageEvent,
        personal: dict,
        rest: str,
    ) -> str:
        if not rest:
            return build_advanced_text(personal)

        parts = rest.split()
        if parts[0].casefold() in CLEAR_WORDS:
            key = self._pref_key(event)
            if len(parts) == 1:
                await self.preferences.clear(key)
                return "已清除全部个人设置"

            field = FIELD_ALIASES.get(normalize_field(parts[1]))
            if field is None:
                return f"未知参数：{parts[1]}"
            updated = dict(personal)
            updated.pop(field, None)
            if field == "audio_kbps":
                updated.pop("keep_audio", None)
            await self.preferences.set(key, updated)
            return f"已清除个人设置中的 {field}"

        changes, error = parse_override_text(rest)
        if error:
            return f"{error}\n发送 /压缩视频 高级 查看可设置项"

        updated = with_quality_reset(personal, changes)
        await self.preferences.set(self._pref_key(event), updated)
        return f"已保存个人设置：{describe_overrides(updated)}"

    # ---------------- 处理流程 ----------------

    async def _process_video(
        self,
        event: AstrMessageEvent,
        video: Video | File,
        target_message_id,
        spec: CompressionSpec,
        *,
        manual: bool,
    ):
        profile = self._profile(event)
        message_id = str(
            getattr(getattr(event, "message_obj", None), "message_id", "") or ""
        )
        dedupe_key = (
            f"{event.get_platform_id()}:{message_id}" if message_id else ""
        )
        if dedupe_key and dedupe_key in self._processing:
            if manual:
                yield event.plain_result("这个视频正在处理中，请稍候")
            return
        if dedupe_key:
            self._processing.add(dedupe_key)

        input_path = None
        started = False
        try:
            input_path = await self._resolve_video_path(video)
            if not input_path or not os.path.exists(input_path):
                if manual:
                    yield event.plain_result("无法获取视频文件")
                return

            original_mb = os.path.getsize(input_path) / (1024 * 1024)
            if not manual:
                try:
                    threshold = float(self.video_config.get("threshold", 300))
                except (TypeError, ValueError):
                    threshold = 300.0
                if original_mb < threshold:
                    return

            if self._progress_allowed(manual):
                yield event.plain_result(
                    f"正在压缩视频 ({original_mb:.1f}MB)..."
                )

            started = await self._mark_emoji(
                event, profile, "start", target_message_id
            )

            semaphore = self._get_semaphore()
            if manual and semaphore.locked():
                yield event.plain_result("前面还有压缩任务，已排队，请稍候...")
            async with semaphore:
                result = await self._compress_video(input_path, spec, profile)

            if result.error:
                yield event.plain_result(f"视频压缩失败：{result.error}")
                return

            if not result.path or not os.path.exists(result.path):
                yield event.plain_result("视频压缩失败：没有生成输出文件")
                return

            if (
                result.size_mb >= original_mb
                and self.video_config.get("skip_if_not_smaller", True)
            ):
                self._remove_quietly(result.path)
                if manual:
                    yield event.plain_result(
                        f"压缩后体积未减小（{original_mb:.1f}MB → "
                        f"{result.size_mb:.1f}MB），已保留原视频"
                    )
                return

            caption = self._build_caption(original_mb, result, spec, profile)
            if result.file_fallback:
                if not profile.supports_file:
                    self._remove_quietly(result.path)
                    yield event.plain_result(
                        "压缩后仍超过平台限制，且当前场景不支持发送文件"
                    )
                    return
                yield event.chain_result(
                    [
                        File(
                            name=os.path.basename(result.path),
                            file=result.path,
                        ),
                        Plain(caption),
                    ]
                )
                return

            yield event.chain_result(
                [Video.fromFileSystem(result.path), Plain(caption)]
            )

        except Exception as e:
            logger.exception(f"视频处理出错: {e}")
            if manual:
                yield event.plain_result("视频处理出错，请稍后重试")
        finally:
            if started:
                await self._mark_emoji(event, profile, "done", target_message_id)
            if dedupe_key:
                self._processing.discard(dedupe_key)
            self._cleanup_input(input_path)

    def _build_caption(
        self,
        original_mb: float,
        result: CompressionResult,
        spec: CompressionSpec,
        profile: PlatformProfile,
    ) -> str:
        accelerator = "GPU" if result.used_gpu else "CPU"
        head = (
            f"视频已压缩：{original_mb:.1f}MB → {result.size_mb:.1f}MB"
        )
        detail = f"{describe_spec(spec)} · {accelerator}"
        if result.file_fallback:
            limit = (
                profile.video_soft_limit_mb
                or profile.video_hard_limit_mb
                or 0
            )
            return (
                f"{head}\n超过平台 {limit}MB 视频限制，"
                f"已作为文件发送（{detail}）"
            )
        return f"{head}（{detail}）"

    # ---------------- 压缩执行 ----------------

    async def _compress_video(
        self,
        input_path: str,
        spec: CompressionSpec,
        profile: PlatformProfile,
    ) -> CompressionResult:
        info = await self._get_video_info(input_path)
        if spec.target_mb and not info.get("duration"):
            logger.warning("无法获取视频时长，忽略目标大小，改用 CRF 编码")
            spec = replace(spec, target_mb=None)

        path, used_gpu = await self._encode(input_path, spec, info)
        if not path:
            return CompressionResult(error="FFmpeg 编码失败")

        size_mb = os.path.getsize(path) / (1024 * 1024)
        limit = profile.video_soft_limit_mb
        hard_limit = profile.video_hard_limit_mb
        if not limit and hard_limit and size_mb > hard_limit:
            # 软限制被关闭时，至少不要超过硬限制
            limit = hard_limit
        if not limit or size_mb <= limit:
            return CompressionResult(
                path=path, size_mb=size_mb, used_gpu=used_gpu
            )

        action = self._oversize_action()
        if action == "file":
            if hard_limit and size_mb > hard_limit:
                # 连文件也超过硬限制，只能先尝试重新压缩
                action = "recompress_then_file"
            else:
                if not profile.supports_file:
                    self._remove_quietly(path)
                    return CompressionResult(
                        error=(
                            f"压缩后仍超过平台限制"
                            f"（{size_mb:.1f}MB > {limit}MB）"
                        )
                    )
                return CompressionResult(
                    path=path,
                    size_mb=size_mb,
                    used_gpu=used_gpu,
                    file_fallback=True,
                )

        try:
            target_mb = float(self.oversize_config.get("target_mb", 25))
        except (TypeError, ValueError):
            target_mb = 25.0
        target_mb = max(5.0, min(2000.0, target_mb))
        try:
            max_attempts = int(self.oversize_config.get("max_attempts", 1))
        except (TypeError, ValueError):
            max_attempts = 1
        max_attempts = max(1, min(5, max_attempts))
        retry_target = min(target_mb, max(5.0, float(limit) - 2.0))

        current = path
        current_size = size_mb
        current_gpu = used_gpu
        for _ in range(max_attempts):
            # 从“无损”降级时给一个合理的默认上限，避免 4K60 直接按 25MB 硬压
            retry_spec = replace(
                spec,
                lossless=False,
                target_mb=retry_target,
                max_height=spec.max_height or 720,
                fps=spec.fps or 30,
            )
            retry_path, retry_gpu = await self._encode(
                input_path, retry_spec, info
            )
            if not retry_path:
                break
            self._remove_quietly(current)
            current = retry_path
            current_size = os.path.getsize(current) / (1024 * 1024)
            current_gpu = retry_gpu
            if current_size <= limit:
                return CompressionResult(
                    path=current, size_mb=current_size, used_gpu=current_gpu
                )

        if hard_limit and current_size > hard_limit:
            self._remove_quietly(current)
            return CompressionResult(
                error=(
                    f"压缩后仍超过平台硬限制（{current_size:.1f}MB > "
                    f"{hard_limit}MB）"
                )
            )

        if action == "recompress_then_file" and profile.supports_file:
            return CompressionResult(
                path=current,
                size_mb=current_size,
                used_gpu=current_gpu,
                file_fallback=True,
            )

        self._remove_quietly(current)
        return CompressionResult(
            error=(
                f"压缩后仍超过平台限制（{current_size:.1f}MB > "
                f"{limit}MB），可尝试 /压缩视频 25MB"
            )
        )

    def _oversize_action(self) -> str:
        text = str(self.oversize_config.get("action", "")).strip().casefold()
        if text in {"发送文件", "file", "文件", "直接发送文件"}:
            return "file"
        if text in {"重新压缩", "recompress", "重压"}:
            return "recompress"
        return "recompress_then_file"

    async def _encode(
        self,
        input_path: str,
        spec: CompressionSpec,
        info: dict,
    ) -> tuple[str | None, bool]:
        temp_dir = get_astrbot_temp_path()
        os.makedirs(temp_dir, exist_ok=True)
        output_path = os.path.join(
            temp_dir, f"compressed_{uuid.uuid4().hex[:8]}.mp4"
        )

        use_nvenc = (
            self._should_use_gpu()
            and bool(self._gpu_available)
            and not spec.lossless
        )
        attempts = [True, False] if use_nvenc else [False]

        for nvenc in attempts:
            cmd = build_ffmpeg_command(
                input_path, output_path, spec, info, nvenc
            )
            if await self._execute_ffmpeg(cmd, output_path):
                return output_path, nvenc
            self._remove_quietly(output_path)
            if nvenc:
                logger.warning("NVENC 编码失败，回退到 CPU 编码")

        return None, False

    async def _execute_ffmpeg(self, cmd: list, output_path: str) -> bool:
        try:
            timeout = float(self.video_config.get("timeout_seconds", 600))
        except (TypeError, ValueError):
            timeout = 600.0
        timeout = max(30.0, min(7200.0, timeout))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.error("视频压缩超时 (%ss)", int(timeout))
                self._remove_quietly(output_path)
                return False

            if proc.returncode == 0 and os.path.exists(output_path):
                if os.path.getsize(output_path) > 0:
                    return True
                logger.error("FFmpeg 输出文件为空")
                self._remove_quietly(output_path)
                return False

            error_msg = stderr.decode("utf-8", "ignore")[-2000:]
            logger.error(
                "FFmpeg 压缩失败 (returncode=%s): %s",
                proc.returncode,
                error_msg,
            )
            self._remove_quietly(output_path)
            return False

        except Exception as e:
            logger.error(f"压缩异常: {e}")
            self._remove_quietly(output_path)
            return False

    def _cleanup_input(self, input_path: str | None) -> None:
        if not input_path:
            return
        if not self.video_config.get("delete_original_after_compress", True):
            return
        try:
            temp_root = os.path.abspath(get_astrbot_temp_path())
            target = os.path.abspath(input_path)
            if os.path.commonpath([temp_root, target]) != temp_root:
                return
            if os.path.exists(target):
                os.remove(target)
        except (OSError, ValueError) as e:
            logger.debug(f"清理原始临时文件失败: {e}")

    @staticmethod
    def _remove_quietly(path: str | None) -> None:
        if not path:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    # ---------------- 会话与命令工具 ----------------

    def _pref_key(self, event: AstrMessageEvent) -> str:
        platform_id = str(
            event.get_platform_id() or event.get_platform_name() or "unknown"
        )
        return (
            f"pref:v1:{platform_id}:{self._scope_id(event)}:"
            f"{event.get_sender_id() or 'unknown'}"
        )

    def _scope_id(self, event: AstrMessageEvent) -> str:
        return str(
            event.get_group_id() or event.get_session_id() or "unknown"
        )

    def _command_tail(self, event: AstrMessageEvent) -> str:
        text = (event.get_message_str() or "").strip()
        text = re.sub(r"^/+", "", text)
        for name in ("压缩视频", "视频压缩"):
            if text == name:
                return ""
            if text.startswith(name) and (
                len(text) == len(name) or text[len(name)].isspace()
            ):
                return text[len(name) :].strip()
        return text
