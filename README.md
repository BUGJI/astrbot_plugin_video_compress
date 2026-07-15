# 视频自动压缩插件 (astrbot_plugin_video_compress)

AstrBot 视频压缩插件 - 自动检测群内视频消息，超过设定大小时自动压缩并发回原群聊。

## 功能特性
<img src="./logo.png" align=right width=200></img>

- **自动压缩**: 群内发送视频超过阈值时自动压缩并发回原群
- **手动压缩**: 通过指令 `/压缩视频` 手动压缩指定视频
- **多种质量预设**: 支持无损压缩、720p/480p/360p、30/60fps 等多种质量选项
- **群组控制**: 支持白名单/黑名单模式控制哪些群组生效
- **临时文件清理**: 压缩完成后自动清理下载的原视频临时文件
- **配置指令**: 支持运行时动态修改配置参数

## 安装要求

- **FFmpeg**: 系统需安装 `ffmpeg` 和 `ffprobe` 且在 PATH 中
  - Ubuntu/Debian: `apt install ffmpeg`
  - CentOS/RHEL: `yum install ffmpeg`
  - Windows: 从 [ffmpeg.org](https://ffmpeg.org/download.html) 下载并添加到 PATH
  - Docker: `apk add ffmpeg` (Alpine) 或 `apt install ffmpeg` (Debian/Ubuntu)
- **独立显卡(可选)**: 用于加速视频的转码速度
  - Docker 请自行修改引用宿主机显卡

## 配置说明

### 视频压缩设置 (video_compress)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `quality` | string | `有损压缩 720p 30` | 压缩质量预设 |
| `auto_compress` | bool | `false` | 是否启用自动压缩 |
| `threshold` | int | `300` | 自动压缩阈值 (MB)，超过此大小触发压缩 |
| `delete_original_after_compress` | bool | `true` | 压缩后是否删除原始临时文件 |

### 压缩质量选项

| 选项 | 分辨率 | 帧率 | 视频 CRF | 音频码率 | 适用场景 |
|------|--------|------|----------|----------|----------|
| `无损压缩` | 保持原分辨率 | 保持原帧率 | 0 (无损) | 复制原音频 | 归档备份 |
| `有损压缩 720p 60` | 720p | 60fps | 23 | 128kbps | 高帧率视频 |
| `有损压缩 720p 30` | 720p | 30fps | 23 | 128kbps | 通用推荐 |
| `有损压缩 480p 60` | 480p | 60fps | 25 | 96kbps | 节省空间+高帧率 |
| `有损压缩 480p 30` | 480p | 30fps | 26 | 64kbps | 极致压缩 |
| `有损压缩 360p 30` | 360p | 30fps | 28 | 48kbps | 最小体积 |

### 群组控制设置 (group_control)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `mode` | string | `白名单` | `白名单` 或 `黑名单` |
| `group_ids` | list | `[]` | 群号列表 |

## 使用指令

### `/压缩视频 [质量]`
手动压缩视频。发送视频或回复视频消息后使用。
- 质量参数可选，默认使用配置中的质量设置
- 示例: `/压缩视频 有损压缩 720p 30`

### `/视频压缩设置 [键] [值]`
查看或修改插件配置。

**查看当前配置:**
```
/视频压缩设置
```

**修改配置示例:**
```
/视频压缩设置 auto_compress true
/视频压缩设置 threshold 100
/视频压缩设置 quality 有损压缩 480p 30
/视频压缩设置 group_mode 白名单
/视频压缩设置 group_add 123456789
/视频压缩设置 group_remove 123456789
```

## 安装方法

1. 将插件目录 `astrbot_plugin_video_compress` 放入 AstrBot 的 `data/plugins/` 目录
2. 重启 AstrBot 或在控制台执行插件重载
3. 在 WebUI 插件管理中启用插件

## 配置文件示例

```json
{
  "video_compress": {
    "quality": "有损压缩 720p 30",
    "auto_compress": false,
    "threshold": 300,
    "delete_original_after_compress": true
  },
  "group_control": {
    "mode": "白名单",
    "group_ids": ["123456789", "987654321"]
  }
}
```

## 权限说明

- 指令默认需要管理员权限或群主权限
- 可通过 AstrBot 权限系统配置指令权限

## 注意事项

1. **FFmpeg 必须可用**: 无 FFmpeg 无法压缩，插件启动时会检测并警告
2. **临时文件存储**: 视频下载和压缩过程使用 AstrBot 临时目录 (`data/temp/`)
3. **大文件处理**: 超大视频压缩可能需要较长时间，默认超时 5 分钟
4. **平台限制**: 不同平台发送视频的大小限制不同，压缩后仍可能超出平台限制
5. **配置持久化**: 通过指令修改的配置仅在内存中，重启后恢复为配置文件值。持久化修改请编辑配置文件
