import os
import asyncio
import uuid
import shutil
from pathlib import Path
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Video, Plain
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path


@register("astrbot_plugin_video_compress", "BUGJI", "视频自动压缩器 - 群内视频自动压缩并发回原群", "1.3.0", "https://github.com/BUGJI/astrbot_plugin_video_compress")
class VideoCompressPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config = context.config.get("video_compress", {})
        self.group_config = context.config.get("group_control", {})

    async def initialize(self):
        logger.info("视频压缩插件已加载")
        if not await self._check_ffmpeg():
            logger.warning("未检测到 ffmpeg/ffprobe，视频压缩功能将不可用")

    async def terminate(self):
        pass

    async def _check_ffmpeg(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    async def _get_video_info(self, file_path: str) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,duration",
                "-of", "csv=p=0",
                file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0 and stdout:
                parts = stdout.decode().strip().split(',')
                if len(parts) >= 4:
                    return {
                        "width": int(parts[0]),
                        "height": int(parts[1]),
                        "fps": eval(parts[2]) if parts[2] else 0,
                        "duration": float(parts[3])
                    }
        except Exception as e:
            logger.debug(f"获取视频信息失败: {e}")
        return {}

    async def _check_group_allowed(self, group_id: str) -> bool:
        mode = self.group_config.get("mode", "白名单")
        group_ids = self.group_config.get("group_ids", [])
        if mode == "白名单":
            return group_id in group_ids
        else:
            return group_id not in group_ids

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        if not self.config.get("auto_compress", False):
            return

        group_id = event.get_group_id()
        if not group_id or not self._check_group_allowed(group_id):
            return

        messages = event.get_messages()
        for msg in messages:
            if isinstance(msg, Video):
                async for result in self._process_video(event, msg):
                    yield result

    async def _process_video(self, event: AstrMessageEvent, video: Video):
        try:
            file_path = await video.convert_to_file_path()
            if not file_path or not os.path.exists(file_path):
                logger.warning(f"视频文件不存在: {file_path}")
                return

            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            threshold_mb = self.config.get("threshold", 300)

            if file_size_mb < threshold_mb:
                return

            quality = self.config.get("quality", "有损压缩 720p 30")
            output_path = await self._compress_video(file_path, quality)

            if output_path and os.path.exists(output_path):
                compressed_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                logger.info(f"视频压缩完成: {file_size_mb:.1f}MB -> {compressed_size_mb:.1f}MB")

                compressed_video = Video.fromFileSystem(output_path)
                yield event.chain_result([compressed_video, Plain(f"视频已压缩: {file_size_mb:.1f}MB -> {compressed_size_mb:.1f}MB")])
            else:
                yield event.plain_result("视频压缩失败")

        except Exception as e:
            logger.error(f"视频处理出错: {e}")
            yield event.plain_result(f"视频处理出错: {e}")

    async def _compress_video(self, input_path: str, quality: str) -> Optional[str]:
        temp_dir = get_astrbot_temp_path()
        os.makedirs(temp_dir, exist_ok=True)
        output_filename = f"compressed_{uuid.uuid4().hex[:8]}.mp4"
        output_path = os.path.join(temp_dir, output_filename)

        if quality == "无损压缩":
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-c:v", "libx264", "-crf", "0", "-preset", "veryslow",
                "-c:a", "copy",
                output_path
            ]
        elif quality == "有损压缩 720p 60":
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", "scale=-2:720,fps=60",
                "-c:v", "libx264", "-crf", "23", "-preset", "medium",
                "-c:a", "aac", "-b:a", "128k",
                output_path
            ]
        elif quality == "有损压缩 720p 30":
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", "scale=-2:720,fps=30",
                "-c:v", "libx264", "-crf", "23", "-preset", "medium",
                "-c:a", "aac", "-b:a", "128k",
                output_path
            ]
        elif quality == "有损压缩 480p 60":
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", "scale=-2:480,fps=60",
                "-c:v", "libx264", "-crf", "25", "-preset", "medium",
                "-c:a", "aac", "-b:a", "96k",
                output_path
            ]
        elif quality == "有损压缩 480p 30":
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", "scale=-2:480,fps=30",
                "-c:v", "libx264", "-crf", "26", "-preset", "medium",
                "-c:a", "aac", "-b:a", "64k",
                output_path
            ]
        elif quality == "有损压缩 360p 30":
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", "scale=-2:360,fps=30",
                "-c:v", "libx264", "-crf", "28", "-preset", "medium",
                "-c:a", "aac", "-b:a", "48k",
                output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", "scale=-2:720,fps=30",
                "-c:v", "libx264", "-crf", "23", "-preset", "medium",
                "-c:a", "aac", "-b:a", "128k",
                output_path
            ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

            if proc.returncode == 0 and os.path.exists(output_path):
                # 清理原始临时文件
                if self.config.get("delete_original_after_compress", True):
                    try:
                        if os.path.exists(input_path) and input_path.startswith(get_astrbot_temp_path()):
                            os.remove(input_path)
                    except Exception as e:
                        logger.debug(f"清理原始临时文件失败: {e}")
                return output_path
            else:
                logger.error(f"FFmpeg 压缩失败: {stderr.decode()}")
                if os.path.exists(output_path):
                    os.remove(output_path)
                return None

        except asyncio.TimeoutError:
            logger.error("视频压缩超时 (5分钟)")
            if os.path.exists(output_path):
                os.remove(output_path)
            return None
        except Exception as e:
            logger.error(f"压缩异常: {e}")
            if os.path.exists(output_path):
                os.remove(output_path)
            return None

    @filter.command("压缩视频")
    async def cmd_compress_video(self, event: AstrMessageEvent, quality: str = ""):
        """压缩视频指令: /压缩视频 [质量]
        质量选项: 无损压缩 / 有损压缩 720p 60 / 有损压缩 720p 30 / 有损压缩 480p 60 / 有损压缩 480p 30 / 有损压缩 360p 30
        回复视频或发送视频后使用此指令"""
        messages = event.get_messages()
        video_msg = None
        for msg in messages:
            if isinstance(msg, Video):
                video_msg = msg
                break

        if not video_msg:
            yield event.plain_result("请发送或回复一个视频后再使用此指令")
            return

        valid_qualities = ["无损压缩", "有损压缩 720p 60", "有损压缩 720p 30", "有损压缩 480p 60", "有损压缩 480p 30", "有损压缩 360p 30"]
        if quality and quality not in valid_qualities:
            yield event.plain_result(f"无效的质量选项，可选: {', '.join(valid_qualities)}")
            return

        quality = quality or self.config.get("quality", "有损压缩 720p 30")

        try:
            file_path = await video_msg.convert_to_file_path()
            if not file_path or not os.path.exists(file_path):
                yield event.plain_result("无法获取视频文件")
                return

            original_size = os.path.getsize(file_path) / (1024 * 1024)
            yield event.plain_result(f"正在压缩视频 ({original_size:.1f}MB)...")

            output_path = await self._compress_video(file_path, quality)

            if output_path and os.path.exists(output_path):
                compressed_size = os.path.getsize(output_path) / (1024 * 1024)
                compressed_video = Video.fromFileSystem(output_path)
                yield event.chain_result([
                    compressed_video,
                    Plain(f"压缩完成: {original_size:.1f}MB -> {compressed_size:.1f}MB ({quality})")
                ])
            else:
                yield event.plain_result("视频压缩失败")

        except Exception as e:
            logger.error(f"指令压缩出错: {e}")
            yield event.plain_result(f"压缩出错: {e}")

    @filter.command("视频压缩设置")
    async def cmd_config(self, event: AstrMessageEvent, key: str = "", value: str = ""):
        """配置视频压缩: /视频压缩设置 [键] [值]
        键值对:
        - auto_compress true/false
        - threshold <MB数值>
        - quality <质量选项>
        - group_mode 白名单/黑名单
        - group_add <群号>
        - group_remove <群号>
        """
        if not key:
            config = self.config
            group_cfg = self.group_config
            yield event.plain_result(
                f"当前配置:\n"
                f"自动压缩: {config.get('auto_compress', False)}\n"
                f"阈值: {config.get('threshold', 300)}MB\n"
                f"质量: {config.get('quality', '有损压缩 720p 30')}\n"
                f"清理原文件: {config.get('delete_original_after_compress', True)}\n"
                f"群组模式: {group_cfg.get('mode', '白名单')}\n"
                f"群组列表: {group_cfg.get('group_ids', [])}"
            )
            return

        if key == "auto_compress":
            self.config["auto_compress"] = value.lower() == "true"
            yield event.plain_result(f"自动压缩已设置为: {self.config['auto_compress']}")
        elif key == "threshold":
            try:
                self.config["threshold"] = int(value)
                yield event.plain_result(f"阈值已设置为: {value}MB")
            except ValueError:
                yield event.plain_result("阈值必须是数字")
        elif key == "quality":
            valid = ["无损压缩", "有损压缩 720p 60", "有损压缩 720p 30", "有损压缩 480p 60", "有损压缩 480p 30", "有损压缩 360p 30"]
            if value in valid:
                self.config["quality"] = value
                yield event.plain_result(f"质量已设置为: {value}")
            else:
                yield event.plain_result(f"无效质量，可选: {', '.join(valid)}")
        elif key == "group_mode":
            if value in ["白名单", "黑名单"]:
                self.group_config["mode"] = value
                yield event.plain_result(f"群组模式已设置为: {value}")
            else:
                yield event.plain_result("模式必须是 白名单 或 黑名单")
        elif key == "group_add":
            try:
                gid = str(value)
                if gid not in self.group_config.get("group_ids", []):
                    self.group_config.setdefault("group_ids", []).append(gid)
                yield event.plain_result(f"已添加群组: {gid}")
            except:
                yield event.plain_result("群号格式错误")
        elif key == "group_remove":
            try:
                gid = str(value)
                if gid in self.group_config.get("group_ids", []):
                    self.group_config["group_ids"].remove(gid)
                yield event.plain_result(f"已移除群组: {gid}")
            except:
                yield event.plain_result("群号格式错误")
        else:
            yield event.plain_result("未知配置项")