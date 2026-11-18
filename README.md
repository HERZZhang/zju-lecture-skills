# zju-lecture-skills

> DeepSeek Harness（DSH）技能包：把浙大 **智云课堂** 回放变成带时间戳的课程知识总结。
>
> 两个 skill：`zju-lecture`（字幕 / PPT / AI 总结 / 课件提取）与 `lecture-transcribe`（Whisper 增强识别）。

## 这是什么

从开源项目 [nzw806/zju-lecture-summerizer-](https://github.com/nzw806/zju-lecture-summerizer-)（MIT）拆出来的
「能力手臂」，按 DSH skill 规范重新打包：核心纯 Python 标准库，CLI 输出 JSON，便于 agent 直接调用。

| skill | 能力 |
|---|---|
| **zju-lecture** | 浙大统一认证登录态复用（DPAPI/Keychain）· 抓语音字幕 · 抓课件 PPT（图片 + 清单）· PPT 视觉转写 · AI 生成五段式课程讲义（速览 / 分章详解 / 公式清单 / 考试信息 / 考点预测）· 课件文字提取（pptx/docx/pdf/txt/md） |
| **lecture-transcribe** | 下载回放视频 → ffmpeg 抽音频 → faster-whisper large-v3 重识别，带防幻觉质量检查 |

## 安装

两个 skill 都是「目录 + SKILL.md」形式，复制到 DSH 用户级 skills 目录即可：

```powershell
git clone https://github.com/HERZZhang/zju-lecture-skills.git
$dst = "$env:USERPROFILE\.dsh\skills"
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item .\zju-lecture-skills\skills\zju-lecture        $dst -Recurse -Force
Copy-Item .\zju-lecture-skills\skills\lecture-transcribe $dst -Recurse -Force
```

安装后 DSH 的 skill 目录会自动扫描到（无需重启）。也可以放到工作区的 `.dsh/skills/`（只对该工作区生效）。

## 依赖

| 依赖 | 用于 | 安装 |
|---|---|---|
| Python 3.9+ | 全部 | 本机建议用 DSH 专用环境 `C:\Users\HerzZhang\anaconda3\envs\dsh-agent\python.exe` |
| Playwright（可选） | `login` 弹窗登录 | `pip install playwright`；优先调用系统 Edge/Chrome，无需下载 Chromium |
| faster-whisper（可选） | 增强识别 | `pip install faster-whisper`（首次自动下载模型，约 3GB） |
| ffmpeg（可选） | 增强识别 | `python transcribe.py run <URL> --download-ffmpeg` 自动下载静态版 |
| DeepSeek API key（可选） | AI 总结 | 也可以用智谱 / 通义 / OpenAI / 任意 OpenAI 兼容端点 |

## 快速开始

```powershell
$py  = 'C:\Users\HerzZhang\anaconda3\envs\dsh-agent\python.exe'
$cli = "$env:USERPROFILE\.dsh\skills\zju-lecture\scripts\zju_zy.py"

& $py $cli status                          # 自检
& $py $cli login                           # 登录一次（弹 Playwright 窗口）
& $py $cli set-key --key "sk-..."          # API key 进系统钥匙串
& $py $cli summarize "<智云课堂回放URL>"    # 抓字幕 + 抓 PPT + 生成知识总结
```

`lecture-transcribe`：

```powershell
$tr = "$env:USERPROFILE\.dsh\skills\lecture-transcribe\scripts\transcribe.py"
& $py $tr status
& $py $tr run "<回放URL>" --download-ffmpeg
```

完整命令、输出结构、排障见各 skill 的 `SKILL.md` 与 `references/`。

## 凭据与安全

- 登录 Cookie、API key **只进系统钥匙串**（Windows DPAPI / macOS Keychain），不写项目文件、不打印明文；
- 密码只进浙大官方登录页，代码不读取、不保存；
- 抓取仅限本人有权限的课程，不批量爬取、不传播课件；
- 沙箱内无法写 `~` 时，密钥目录自动回退到当前目录 `.zju-secret-store/`（仍是 DPAPI 密文）。

## 来源与许可

- 核心代码源自 [nzw806/zju-lecture-summerizer-](https://github.com/nzw806/zju-lecture-summerizer-)（MIT），
  本仓库做了拆分、CLI 封装、沙箱回退、系统浏览器适配等改动；
- 本仓库同样采用 [MIT](LICENSE) 许可，保留上游版权声明。

## 已知限制

- 登录需要真人完成浙大统一身份认证（验证码 / 密码），agent 无法代替；
- 平台字幕接口 2026-11 起必须带登录态（匿名 403）；
- 视觉转写按页计费（约 1k token/页），想省钱用 `--no-ppt`；
- 增强识别模式单节课约 10–30 分钟（CPU）。
