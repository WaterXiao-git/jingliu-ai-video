# 镜流工作台 HTTP API 参考

基础地址：`http://127.0.0.1:7861`（默认，以安装配置为准）。仅监听本机，
非 GET/HEAD 请求只接受本机来源。`scripts/jingliu.py` 已封装以下全部端点；
如需直接调用（curl 等），可直接使用本表。

## 服务状态

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/status` | GET | `comfy`（视频引擎就绪）、`ollama`（本地编剧）、`workflow`、`models`（Ollama 模型列表）、`voices`（声线表）、`h3_confirmed`（模型许可已确认） |
| `/api/identity` | GET | `{app:"jingliu", workspace:<哈希>}`，用于确认连的是镜流工作台 |

## 项目

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/projects` | GET | 项目卡片列表（id/name/aspect/updated/shots/cover/exports） |
| `/api/projects` | POST | `{name, aspect:"9:16"|"16:9"}` → 完整项目对象 |
| `/api/sample` | POST | 导入内置「月台机器人」示例 |
| `/api/projects/{id}` | GET | 完整项目数据（assets/shots/draft/exports/script 等） |
| `/api/projects/{id}` | PATCH | 改 `name`(≤100)、`brief`(≤6000)、`script`(≤20000)、`track`（音轨相对路径） |

## 素材与媒体

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/projects/{id}/upload` | POST | multipart 字段 `file`；支持 PNG/JPG/WebP/MP4/MOV/WebM/MKV/常见音频；单文件 ≤300MB；返回 `{file:"assets/<uid><ext>"}` |
| `/media/{project}/{category}/{name}` | GET | 取媒体文件；`?download=1` 作为附件下载。生成的镜头视频与导出成片在 `renders/<job_id>.mp4`（字幕 `.srt`），上传素材在 `assets/`；具体路径以项目对象的 `shots[].clip`、`exports[].file` / `exports[].subtitle` 为准 |

**写操作防跨站要求**：非 GET 请求必须携带 `X-Studio-Request: 1` 头（`Origin` 为空或与工作台同源），
否则返回 403「请从本机工作台页面发起操作。」`scripts/jingliu.py` 已自动处理。
API 错误对 `/api/` 路径返回 JSON `{"error": "<中文提示>"}`。
| `/api/projects/{id}/assets` | POST | 素材增删改：`{id?, name, kind:"character"|"scene"|"prop", image?, prompt?, voice?, remove?}`。`voice` 必须在 `status.voices` 中；素材名与台词角色名一致才能按角色配音 |

## 分镜

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/projects/{id}/shots` | POST | `{action, ...}`，action ∈：|

- `add`：追加空镜头（项目 ≤60 镜）
- `save`：`{id, title?(≤100), visual?(≤3000), prompt?(≤8000), dialogue?(≤2500), first?, last?, clip?, quality?: "quick"|"normal"|"detail", seconds?: 0.5–12, seed?: 0–4294967295}`
- `remove` / `up` / `down`：`{id}`

首帧/尾帧为图片相对路径；`clip` 为已生成视频相对路径，换新 clip 时旧 clip 归档进 `versions`。

## 任务

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/jobs` | GET | 全部任务（含 state/progress/message/created） |
| `/api/projects/{id}/jobs` | POST | 排队任务，`kind` 决定类型：|
| `/api/jobs/{job}/retry` | POST | 仅 `failed` 任务可重试 |
| `/api/jobs/{job}/cancel` | POST | 仅 `queued` 任务可取消 |

任务类型（`kind`）：

- `video`：`{steps?: 4–40 默认 20, shot_id?}`。省略 `shot_id` 时生成**所有**「有首帧且无 clip」的镜头。
  要求：镜头有 `first`；有 `prompt` 或 `visual`；工作台启动前已确认 H3 许可（`h3_confirmed`）。
- `image`（草图）：`{asset_id}`（素材需有 `prompt` 且无 `image`）或 `{shot_id}`（镜头需无 `first` 且有 `visual`/`prompt`）。
- `draft`（编剧草案，需 Ollama）：`{brief(≤10000), count: 1–12, seconds: 5–120, model?}`。
  完成后通过 `/apply-draft` 导入：最多 20 镜、自动带出建议素材与剧本。
- `export`：`{size:"720"|"1080", subtitles:bool, audio:"source"|"tts"|"track"|"silent", voice, name?}`。
  每个镜头须有 `clip` 或 `first`；`audio:"track"` 需项目已设置音轨。

任务状态流转：`queued → running → done | failed`，另可 `cancelled`。
终端状态集合：`{done, failed, cancelled}`。

## 可用声线（VOICES）

| 键名 | 说明 |
| --- | --- |
| `local-zh-female` | 本地中文女声（Windows 系统语音，离线默认） |
| `local-zh-male` | 本地中文男声（需系统已装中文男声语音包） |
| `zh-CN-XiaoxiaoNeural` | 晓晓 · 青年女声（联网 Edge TTS） |
| `zh-CN-XiaoyiNeural` | 晓伊 · 活泼女声（联网） |
| `zh-CN-YunxiaNeural` | 云夏 · 少年男声（联网） |
| `zh-CN-YunxiNeural` | 云希 · 青年男声（联网） |
| `zh-CN-YunjianNeural` | 云健 · 沉稳男声（联网） |

## 错误格式

非 2xx 返回中文错误信息（如「请为镜头设置首帧。」「采样步数请使用 4–40 的整数。」），
`/api/` 路径为 JSON `{"error": "..."}`，媒体等路径为纯文本，HTTP 400/403/404/409 等。
CLI 会将其透传到 stderr 并以非零码退出。
