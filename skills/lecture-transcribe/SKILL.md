---
name: lecture-transcribe
description: 智云课堂「增强识别」：下载回放视频 → ffmpeg 抽音频 → faster-whisper（默认 large-v3）重新转写整课文字，带防幻觉质量检查。当平台字幕识别太差（口音重、术语错、缺字漏句），或老师要求「重新转写 / 自己识别一遍」时使用。
whenToUse: 用户对平台字幕质量不满、要求 Whisper 重新识别课程、或需要一份干净的可检索转写稿时。
---

# 智云课堂增强识别（lecture-transcribe）

平台字幕来自别人的语音识别，口音重或术语多时错误不少。本 skill 下载回放视频，
用 **faster-whisper large-v3** 自己重识别一遍，输出带时间戳的干净全文。

> 这是一条「重」手臂：单节课要下载 1–2GB 视频、跑 10–30 分钟识别，
> 首次还要下载约 3GB 模型。**只在平台字幕确实不行时用**，日常总结优先 `zju-lecture`。

## 前置条件

| 项 | 说明 | 检查 |
|---|---|---|
| `zju-lecture` skill | **必须**，本 skill 复用它来读登录态（DPAPI）与解析 URL | 不存在会直接报错并提示 |
| ffmpeg | 抽音频用；可 `--download-ffmpeg` 自动下（约 20MB） | `status` 的 `ffmpeg` |
| faster-whisper | `& C:\Users\HerzZhang\anaconda3\envs\dsh-agent\python.exe -m pip install faster-whisper`（写 anaconda3\envs 需提权） | `status` 的 `faster_whisper.installed` |
| 登录态 | 视频直链需要 Cookie | `status` 的 `cookie.valid` |
| 磁盘 | 至少几 GB 空闲（视频 + 模型缓存） | — |

## 命令

```powershell
$py = 'C:\Users\HerzZhang\anaconda3\envs\dsh-agent\python.exe'
$cli = '<本 skill 目录>\scripts\transcribe.py'

# 环境自检
& $py $cli status

# 跑增强识别（首次会自动下载模型）
& $py $cli run "<回放URL>" --download-ffmpeg

# 常用变体
& $py $cli run "<回放URL>" --model large-v3 --keep-video   # 保留视频便于复盘
& $py $cli run "<回放URL>" --courseware 课件.pptx           # 用课件补术语提示
& $py $cli run "<回放URL>" --video-url "<mp4直链>"          # 直接给视频地址
```

`run` 参数：`--out`（默认 `./lecture-transcribe-output`）、`-o`（输出文件）、
`--model`、`--courseware`、`--video-url`、`--ffmpeg`、`--download-ffmpeg`、
`--keep-video`、`--force`（重新下载/重识别）、`--cookie`（不推荐，会进命令历史）。

## 流程与输出

```
URL → get-config 拿 mp4 直链 → 下载 video.mp4 → ffmpeg 抽 16kHz 单声道 mp3
    → faster-whisper large-v3 转写（中性提示词 + condition_on_previous_text=False）
    → 防幻觉质量检查 → transcript_whisper.txt
```

```
<out>/<YYYYMMDD>_sub<sub_id>/
  raw/video.mp4 / audio.mp3              # 默认跑完删除（--keep-video 保留）
  transcript_whisper.txt                 # 逐段带 [时:分:秒]
  transcript_whisper_by_minute.txt       # 按分钟合并
```

跑完后的 `transcript_whisper.txt` 是干净转写稿，可以直接发给老师；也可作为
`zju-lecture summarize --courseware <该文件>` 的术语参考（summarize 仍以平台字幕为
正文来源，`--courseware` 只做校准；如果需要完全用 Whisper 稿做总结，先和老师确认再扩展）。

## 防幻觉机制（内置，别关）

- 提示词中性、只补课件术语，不写死课程名；
- `condition_on_previous_text=False`，切断错误跨窗口传播；
- 质量检查：单一文本 ≥30% / 多样性 <20% / 幻觉句占比 ≥50% → **中止**并明确报错，
  不把垃圾送进 AI 总结；
- 命中检查时先确认音轨正常，再考虑换模型或提高音量后重跑。

## 排障

| 症状 | 处理 |
|---|---|
| `需要 faster-whisper` | 按上表装包（提权写 anaconda3\envs） |
| `缺少依赖 skill` | 先装 `zju-lecture` skill，再重跑 |
| `拿不到视频直链` | 登录态过期 → 先 `zju-lecture` 的 `login`；或 `--video-url` 手动给直链 |
| `ffmpeg 抽音频失败` | 改用 `--download-ffmpeg` 的内置二进制；确认视频完整（下载中断会重跑） |
| 识别很慢 | 正常（large-v3 CPU 约 10–30 分钟/课）；GPU 可用时自动加速 |
| 中途中断 | 重跑会复用已下载的视频；加 `--force` 强制重来 |
| 磁盘不够 | 加 `--keep-video` 前先清理旧 `raw/`；模型缓存在 `~/.cache/huggingface` |
