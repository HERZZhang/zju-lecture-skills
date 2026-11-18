# 智云课堂接口与鉴权细节

> 这些事实读自上游代码（`pipeline.py`）并经实际请求验证过；属于「排障时对照」用，
> 日常使用不需要读。

## 站点与端点

| 用途 | 方法 / 路径 | 备注 |
|---|---|---|
| 主站 | `https://classroom.zju.edu.cn` | 所有主接口 |
| 备用后端 | `https://interactivemeta.cmc.zju.edu.cn` | 主站空/坏时回退 |
| 字幕 | `GET /courseapi/v3/web-socket/search-trans-result?sub_id=<id>&tenant_code=<112>` | 匿名 403（2026-11 起），必须带登录态 |
| 登录态校验 | `GET /userapi/v1/infosimple` | 返回 `params.id` / `realname` / `tenant_id` |
| PPT 列表 | `GET /pptnote/v1/schedule/search-ppt?course_id=<id>&sub_id=<id>&page=<n>&per_page=100` | 主站；备用 `interactivemeta.../pptnoteapi/v1/schedule/search-ppt` |
| 视频直链 | `GET /courseapi/v2/play-template/get-config?course_id=&sub_id=&tenant_code=` | 返回 JSON 里递归找第一个 `.mp4` 直链 |
| 匿名 PPT 文字层 | `GET /pptnote/v1/schedule/search-ppt?sub_id=&tenant_code=` | 旧接口，失败不阻塞 |

## 鉴权：Cookie + Bearer

1. 登录页：浙大统一身份认证（`zjuam.zju.edu.cn` 域），登录成功后浏览器持有
   `classroom.zju.edu.cn` 的会话 Cookie。
2. 请求带 `Cookie: <全部 cookie>`，同时从 Cookie 的 `_token` 解出 token：
   - `_token` 是 **URL 编码的 PHP 序列化串**，形如
     `{i:0;s:6:"_token";i:1;s:N:"<token>";}`；
   - 先 `urllib.parse.unquote` 再正则提取 `<token>`；
   - 请求头加 `Authorization: Bearer <token>`。
3. 浏览器 UA 固定为 Chrome 120（`pipeline.UA`）。
4. PPT 图片下载只允许这些域名后缀（防把 Cookie/请求发到意外主机）：
   `.zju.edu.cn` / `.chinamcloud.com` / `.chinamcloud.cn` / `.chinamcache.com`，
   且强制 https。

## 返回数据形态

- 字幕：`{"code":0, "list":[{"all_content":[{"BeginSec":123,"Text":"..."}]}]}`
  - `BeginSec` 是相对回放开头的秒数，按它排序；
  - 空文本段会被过滤；无字幕（直播未结束）时报错。
- PPT：`{"code":0, "list":[...], "total":N}`，每条：
  - `content` 是 JSON 字符串，含 `pptimgurl`（原图）/ `pptthumb`（缩略图）/
    `content`（文字层，多数课为空）/ `created`（毫秒时间戳）；
  - `created_sec` 是该页在回放中投出的秒数（部分课才给）。
- 视频：`get-config` 返回嵌套 JSON，递归找 `http*.mp4`。

## 分块策略

- 字幕按分钟合并后，每块不超过 **11000 字符**（`chunk_minutes`）；
- 单次总结请求超出模型上下文（HTTP 400）才退化为顺序分块 + 合并；
- 视觉转写按每 10 页一组并发（最多 10 组），组内顺序。

## 上游已知 bug（已在 skill 副本中修复）

`deepseek_chat()` 原实现硬编码 `https://api.deepseek.com/chat/completions`，
`base_url` 参数虽存在但未用于请求，导致选智谱/千问/OpenAI 时实际仍打 DeepSeek。
skill 里已改为 `base_url or DEEPSEEK_URL`。
