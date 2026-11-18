# zju-lecture 排障手册

按症状查。每条给「先查什么 → 怎么修」。

## 1. 字幕接口 403 / 抓取失败

**症状**：`fetch` 返回 `字幕接口抓取失败（HTTP 403）` 或 `code=...`。

- 2026-11 起平台**不再匿名开放字幕**，403 基本等于没有有效登录态。
- 先跑 `status`：`cookie.valid` 是否为 `true`？`false` 就 `login`（`--force` 强制重登）。
- 若 `status` 里 `cookie.present=true` 但 `valid=false`：登录态过期，重新登录；
  DPAPI 里残留的旧 Cookie 会被新登录覆盖。
- 平台偶发抖动：等 1–2 分钟后重试一次。

## 2. 登录（Playwright）相关

| 症状 | 处理 |
|---|---|
| `Playwright 安装失败` | 手动装：`& <dsh-agent python> -m pip install playwright`（需要提权写 anaconda3\envs） |
| `Chromium 下载失败` | `& <python> -m playwright install chromium`（约 150MB，一次） |
| 弹窗打不开 / 启动失败 | 确认有桌面会话（远程/无头环境不行）；或改用「手动粘贴 Cookie」兜底（见下） |
| 登录超时（默认 5 分钟） | 重新 `login`，确认浏览器窗口在桌面上没有被遮挡 |
| 登录后仍校验失败 | 换 `--force` 重登；确认登录的是**老师本人**账号且有该课程权限 |

**手动粘贴 Cookie 兜底**：从老师已登录的浏览器里导出 `classroom.zju.edu.cn`
的 Cookie 字符串（`name=value; name2=value2`），本 skill 暂未提供 CLI 入口——
如需临时使用，可让老师把 Cookie 给脚本内部调用，但**不要写进日志或聊天记录**。

## 3. PPT 抓不到 / 为空

- `status` 里 `cookie.valid` 必须是 `true`（PPT 接口需登录）。
- 返回 `没有可用的 PPT 幻灯片`：该课本身没上传 PPT，或老师只讲了板书——正常，不影响字幕总结。
- 主站 401/403 会自动给明确报错；主站空列表会回退 `interactivemeta` 后端。
- 图片下载个别失败：manifest 里该页 `status` 非 `ok`，其余照常，不阻塞。

## 4. `--vision` 视觉转写失败

- **所选服务商没有可用的视觉模型**：连续 3 页失败会自动停止（PPT 图片仍已保存）。
  换 DeepSeek（`--provider deepseek`，视觉模型 `deepseek-flash`）重试。
- `API key 无效（401）`：key 与 provider 不匹配，或 key 过期。
- 视觉转写是主要 token 消耗（约 1k token/页，60 页课 ≈ 6 万 token），想省钱就别加 `--vision`。

## 5. AI 总结相关

| 症状 | 原因 / 处理 |
|---|---|
| `API 账户余额不足（402）` | 充值 |
| `HTTP 429` | 限流，脚本自带退避重试；持续失败换 provider 或稍后 |
| `HTTP 400` 且提示 context | 字幕超上下文 → 脚本自动退化为分块+合并（不并行，确定性顺序） |
| 总结很慢 | 单次请求整课字幕属正常（2–4 分钟） |
| 输出缺结构 | 检查提示词是否被 `--extra` 意外覆盖；默认五段式结构是内置的 |
| 术语错字多 | 加 `--courseware 课件文件` 或用 `ppt --vision` 提供权威文字层，总结会按它纠错 |

## 6. 字幕/识别质量检查中止

`check_transcript_quality` 会在以下情况中止并报错（防把垃圾送进 AI）：
- 单一文本占比 ≥30%（同一句反复出现）；
- 总段数 ≥20 且不同文本占比 <20%；
- ≥50% 的段包含「点赞/订阅/字幕提供」等幻觉句。

平台字幕命中时多半是**音频真的有问题**（或直播未结束）。Whisper 模式见
`lecture-transcribe` skill 的排障。

## 7. 其他环境问题

- **macOS 证书**：官方 Python 缺根证书时脚本降级不校验并提示；根治：
  `/Applications/Python 3.x/Install Certificates.command`。
- **HTTPS 代理**：本机走 Clash（`http://127.0.0.1:7890`）。脚本用 Python
  `urllib`（OpenSSL），直连即可；如需代理，设环境变量
  `HTTP_PROXY`/`HTTPS_PROXY`（`urllib` 自动读取）。
- **输出目录**：`--out` 默认 `./zju-lecture-output`；QQ 通道下 cwd 通常就是工作区，
  产物在工作区里，可直接发给老师。
