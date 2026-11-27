# 视频自动压缩插件 (astrbot_plugin_video_compress)

AstrBot 视频压缩插件：自动检测群内/单聊的视频消息，超过阈值时自动压缩并发回原会话；也可以手动压缩指定或引用的视频。

支持 **OneBot v11（aiocqhttp）** 与 **QQ 官方机器人（qq_official / qq_official_webhook）**，会根据平台能力自动调整行为。

## 功能特性

- **自动压缩**：群聊/单聊视频超过阈值时自动压缩并发回
- **手动压缩**：`/压缩视频` 压缩当前视频或引用视频
- **平台自适应**：QQ 官方不支持贴表情、视频约 30MB 软限制、被动回复次数有限；插件会自动跳过表情并在超限时重压或转为文件
- **个人默认参数**：每个用户在当前群/会话内保存自己的默认压缩参数（QQ 官方用户 ID 在不同群不同，因此不做跨群跟随）
- **简易预设 + 高级参数**：`720p30`、`480p30`、`25MB` 等，也支持 CRF、帧率、分辨率、音频码率
- **体积优先**：压缩后没有变小时默认不发送，避免“越压越大”
- **GPU 加速**：检测到 NVENC 时自动使用，失败回退 CPU
- **并发控制**：默认同时只压缩一个视频，避免占满 CPU/GPU
- **临时文件清理**：压缩完成后自动删除下载的原视频临时文件

## 安装要求

- **FFmpeg**：系统需安装 `ffmpeg` 和 `ffprobe`，并在 PATH 中
  - Ubuntu/Debian：`apt install ffmpeg`
  - CentOS/RHEL：`yum install ffmpeg`
  - Windows：从 [ffmpeg.org](https://ffmpeg.org/download.html) 下载并加入 PATH
  - Docker：`apk add ffmpeg`（Alpine）或 `apt install ffmpeg`（Debian/Ubuntu）
- 可选：NVIDIA GPU + 支持 NVENC 的 ffmpeg，用于硬件加速

## 安装方式

1. 将本插件目录放入 AstrBot 的 `data/plugins/` 目录
2. 重启 AstrBot，或在 WebUI 插件页重载
3. 在 WebUI 的插件配置中按需调整参数

## 配置说明

### 视频压缩（video_compress）

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `quality` | string | `有损压缩 720p 30` | 全局默认压缩预设 |
| `use_gpu` | string | `auto` | `auto` / `enabled` / `disabled` |
| `auto_compress` | bool | `false` | 是否自动压缩群聊视频 |
| `auto_compress_private` | bool | `false` | 是否自动压缩单聊视频 |
| `threshold` | int | `300` | 自动压缩阈值（MB） |
| `delete_original_after_compress` | bool | `true` | 压缩后删除原视频临时文件 |
| `skip_if_not_smaller` | bool | `true` | 压缩后未变小时不发送 |
| `timeout_seconds` | int | `600` | 单个视频压缩超时（秒） |
| `max_concurrent` | int | `1` | 同时压缩数量（1~8） |
| `progress_message` | string | `自动` | `自动` / `总是` / `关闭` |

表情相关配置（`emoji_processing_*`、`emoji_done_*`）仅在 OneBot 且协议端支持贴表情时生效，QQ 官方会忽略。

### 平台适配（platform）

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `mode` | string | `自动` | `自动` / `OneBot` / `QQ 官方` |
| `emoji` | string | `自动` | `自动` / `开启` / `关闭` |
| `qq_official_video_soft_limit_mb` | int | `30` | QQ 官方视频软限制 |
| `qq_official_video_hard_limit_mb` | int | `200` | QQ 官方视频硬限制 |

### 超限处理（oversize）

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `action` | string | `重新压缩后仍超限则发送文件` | `重新压缩` / `发送文件` / `重新压缩后仍超限则发送文件` |
| `target_mb` | int | `25` | 重新压缩的目标大小 |
| `max_attempts` | int | `1` | 重压尝试次数（1~5） |

### 群组控制（group_control）

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `mode` | string | `白名单` | `白名单` / `黑名单` / `全部` |
| `group_ids` | list | `[]` | 群号列表；QQ 官方使用 `group_openid`，可在 `/压缩视频 状态` 查看 |

## 使用说明

### 手动压缩

```text
/压缩视频                 使用当前个人默认/全局默认
/压缩视频 720p30          本次使用 720p30 预设
/压缩视频 25MB            本次按目标大小压缩
/压缩视频 有损压缩 480p 30 支持带空格的完整预设名
```

先发送视频，或回复一条视频消息，再发送命令。

### 帮助与状态

```text
/压缩视频 帮助            查看完整用法
/压缩视频 状态            查看平台能力、当前生效参数、个人默认、会话 ID
/压缩视频 高级            查看高级参数说明
```

### 个人默认（仅当前群/会话）

```text
/压缩视频 默认 720p30
/压缩视频 默认 25MB
/压缩视频 默认 清除
```

个人默认按“平台实例 + 群/会话 + 用户”隔离。QQ 官方机器人在不同群里的用户 openid 不同，因此个人默认不会跨群跟随。

### 高级参数

```text
/压缩视频 设置 crf 22
/压缩视频 设置 max_height 1080 fps 60
/压缩视频 设置 target_mb 25MB
/压缩视频 设置 audio_kbps 0
/压缩视频 设置 preset slow
/压缩视频 设置 清除 crf
/压缩视频 设置 清除
```

| 参数 | 说明 |
|---|---|
| `quality` | 切换预设（会清除同层高级参数） |
| `target_mb` | 目标文件大小（MB） |
| `max_height` | 1080 / 720 / 480 / 360 / source |
| `fps` | 60 / 30 / 24 / source |
| `crf` | 0~51，越小越清晰、文件越大 |
| `audio_kbps` | 0 / 64 / 96 / 128 / 192，0 表示静音 |
| `preset` | ultrafast / fast / medium / slow / veryslow |
| `keep_audio` | 开 / 关 |

## 平台差异

### OneBot v11

- 支持贴表情（取决于协议端是否实现 `set_msg_emoji_like`，不支持时自动忽略）
- 群号是数字 QQ 群号
- 没有内置的视频 30MB 软限制

### QQ 官方机器人

- **不支持贴表情**，插件会跳过表情操作
- 视频软限制约 **30MB**，超过会降级成文件；插件会按 `oversize` 配置重压或转为文件
- 群聊被动回复 60 分钟内约 5 次，单聊约 4 次；自动压缩默认不发送进度提示以节省额度
- 群号是 `group_openid`，不是数字群号
- 频道场景不支持文件消息，超限时只能重压或报错

## 预设参考

| 预设 | 分辨率 | 帧率 | 视频 CRF | 音频码率 | 适用场景 |
|---|---|---|---|---|---|
| `无损压缩` | 原始 | 原始 | 0 | 原始音频（copy） | 归档 |
| `有损压缩 720p 60` | 720p | 60 | 23 | 128kbps | 高帧率视频 |
| `有损压缩 720p 30` | 720p | 30 | 23 | 128kbps | 通用推荐 |
| `有损压缩 480p 60` | 480p | 60 | 25 | 96kbps | 省空间 + 高帧率 |
| `有损压缩 480p 30` | 480p | 30 | 26 | 64kbps | 进一步压缩 |
| `有损压缩 360p 30` | 360p | 30 | 28 | 48kbps | 最小体积 |

## 注意事项

- 压缩是 CPU/GPU 密集型操作，默认 `max_concurrent=1`，避免多个任务同时运行拖慢机器
- QQ 官方超限重压会增加处理时间；如果更在意速度，可将 `oversize.action` 改为 `发送文件`
- 个人默认参数保存在插件 KV 存储中，重启不丢；换群后需要重新设置（QQ 官方用户 ID 按群隔离）
- 全局默认参数请在 WebUI 插件配置中修改；插件不再提供聊天内全局设置命令
