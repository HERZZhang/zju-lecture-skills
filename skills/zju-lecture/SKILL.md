---
name: zju-lecture
description: 浙大智云课堂（classroom.zju.edu.cn）回放采编：抓语音字幕、抓课件 PPT（图片 + 视觉转写）、用 AI 生成带时间戳的课程知识总结，以及从课件文件（pptx/docx/pdf/txt/md）提取文字。当老师给出智云课堂回放链接、要求总结某节课 / 抓字幕 / 抓课件 PPT / 提取课件文字，或排查智云课堂抓取问题时使用。
whenToUse: 用户提供智云课堂回放 URL（classroom.zju.edu.cn 或 interactivemeta.cmc.zju.edu.cn），或明确要求「总结课程 / 抓字幕 / 抓 PPT / 提取课件」，或询问该能力怎么用、为什么抓不到时。
---

# 智云课堂采编（zju-lecture）

把「智云课堂回放 URL」变成「带时间戳的课程知识总结」的本地能力包。核心流程：

```
URL → 解析 sub_id → 抓平台语音字幕（需登录态）→（可选）抓 PPT 图片并视觉转写
    → AI 课程画像（2 秒）→ AI 单次生成五段式讲义 → 落盘 知识总结.md + raw/ + ppt/
```

## 前置条件（先检查，缺什么补什么）

| 项 | 要求 | 怎么检查 |
|---|---|---|
| Python | 本机固定用 `C:\Users\HerzZhang\anaconda3\envs\dsh-agent\python.exe`（3.12） | `status` 里 `python` 字段 |
| 登录态 | 抓字幕/PPT/视频都必须带浙大统一身份认证的 Cookie（2026-11 起匿名 403） | `status` 里 `cookie.valid` |
| API key | 只有 `summarize` 需要（DeepSeek 默认，约 ¥0.1–0.2/课）；只抓字幕不需要 | `status` 里 `api_key.present` |
| ffmpeg | 只有增强识别（Whisper）需要，主流程不需要 | `status` 里 `ffmpeg` |

全都通过 `zju_zy.py status` 一眼看。**登录态和 key 都由用户个人掌握**：登录必须真人输密码，key 由用户提供后写入系统 DPAPI，不要在聊天里回显明文。

## 命令速查

所有命令统一：
- 脚本入口：`<本 skill 目录>/scripts/zju_zy.py`
- **stdout = JSON**（成功 `{"ok": true, ...}`，失败 `{"ok": false, "error": "..."}` + 非零退出码）
- 进度日志走 stderr，不污染 JSON
- Windows 下用 `& <python> zju_zy.py ...` 调用

```powershell
$py = 'C:\Users\HerzZhang\anaconda3\envs\dsh-agent\python.exe'
$cli = '<本 skill 目录>\scripts\zju_zy.py'

# 自检（登录态 / key / ffmpeg / 后端存储）
& $py $cli status

# 登录一次（Playwright 窗口；优先用系统 Edge/Chrome，无需额外下载浏览器内核）
& $py $cli login [--timeout 300]   # 已登录自动复用；--force 强制重登

# API key 存进系统钥匙串（DPAPI 加密，不落明文）；clear-key 清除
& $py $cli set-key --key "sk-..."   # 省略 --key 会从终端隐藏输入
& $py $cli clear-key

# 退出登录（清除本地登录态）
& $py $cli logout

# 只抓字幕（+ 可选下载 PPT 图片；--vision 才做视觉转写，会消耗 token）
& $py $cli fetch "<回放URL>" [--ppt] [--vision]

# 抓 PPT 幻灯片（图片 + manifest；--vision 逐页转写文字）
& $py $cli ppt "<回放URL>" [--vision]

# 完整总结（默认会抓 PPT；--no-ppt 省钱模式；--courseware 附课件校准术语）
# summarize 默认自动生成 PDF（知识总结.pdf，KaTeX 公式渲染）；--no-pdf 可关闭
& $py $cli summarize "<回放URL>" [--no-ppt] [--no-pdf] [--courseware 课件.pptx] [--extra "额外要求"]

# 把已有讲义 Markdown 渲染成 PDF（公式用本地 KaTeX，Edge 打印）
& $py $cli pdf <知识总结.md> [--out 输出.pdf]

# 课件提取纯文字（不打 AI，秒回）
& $py $cli extract <文件> [--out 输出.md]

# 列出内置 API 提供商（deepseek / zhipu / qwen / openai / custom）
& $py $cli providers
```

AI 参数（`fetch --vision` / `ppt --vision` / `summarize` 通用）：
`--key`（缺省读钥匙串）、`--provider deepseek|zhipu|qwen|openai|custom`、
`--base-url`、`--chat-model`、`--vision-model`。

## 典型工作流

**① 总结一节课（最常用）**
1. `status` → 确认 `cookie.valid=true`、`api_key.present=true`
2. 若登录态失效 → `login`（让老师在弹窗里登录，最多等 5 分钟）
3. `summarize "<URL>"` → 从返回 JSON 的 `summary_path` / `pdf_path` 取讲义
4. 把 `知识总结.pdf` 发回给老师（QQ 通道用 `[SEND_FILE: <绝对路径>]`），Markdown 留档

**② 只要字幕存档**：`fetch "<URL>"` → 读 `transcript_path`

**③ 需要课件内容但平台没文字层**：`ppt "<URL>" --vision` → 读 `ppt/ppt_text.txt`

**④ 平台字幕识别差**：改用 `lecture-transcribe` skill（Whisper 重新识别）

## 输出结构

```
<out>/<YYYYMMDD>_sub<sub_id>/
  知识总结.md               # summarize 产物：速览表 / 分章详解 / 公式清单 / 考试信息 / 考点预测
  知识总结.pdf              # 自动转的 PDF（A4、KaTeX 公式、中文排版）；--no-pdf 时不生成
  raw/transcript.txt        # 逐段字幕，带 [时:分:秒]
  raw/transcript_by_minute.txt
  ppt/001_t125s.jpg …       # PPT 页图，文件名带投出秒数
  ppt/manifest.md / .json   # 时间戳 → 图片 → 文字层
  ppt/ppt_text.txt          # 视觉转写/平台文字层
```

`--out` 默认是当前工作目录下 `zju-lecture-output/`。同一课同一天复用目录。

## 关键纪律

- **Cookie / API key 是老师个人凭据**：只允许进系统钥匙串（Windows DPAPI / macOS Keychain），不写项目文件、不打印明文、不发给任何第三方。本 CLI 从不回显它们。
- **密钥目录**：默认 `~/.zju_lecture_summarizer`（DPAPI 密文）；若沙箱不允许写 `~`，自动回退到当前目录 `.zju-secret-store/`（同样密文）。
- **抓取只限本人有权限的课**：不做批量爬取，不传播课件。
- 总结提示词已内置五段式结构；`--extra` 只是追加要求，不要覆盖默认结构。
- 长视频（1–2GB）下载、Whisper 重识别都很慢：明确告诉老师在跑，不要静默等待。
- 单次总结超出上下文时脚本会自动退化为分块+合并，无需干预。

## 排障

抓不到字幕 / 403 / 登录态过期 / PPT 为空 / `--vision` 失败 / 上下文超限 / 字幕幻觉等，先看
[`references/troubleshooting.md`](references/troubleshooting.md)；接口与鉴权细节见
[`references/api.md`](references/api.md)。

## 来源与许可

脚本核心源自开源项目 [nzw806/zju-lecture-summerizer-](https://github.com/nzw806/zju-lecture-summerizer-)（MIT），
按「手臂」拆装进本 skill；`scripts/LICENSE` 保留原许可声明。
