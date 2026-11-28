---
name: jingliu-video
description: 操作镜流（Jingliu）本地 AI 短剧工作台：硬件检查与部署、创建项目、上传角色参考图、编写分镜、生成镜头视频、配音字幕、导出 MP4。Use when the user wants to deploy, run, or create AI short-drama videos with the local Jingliu workbench (镜流), generate shots with MiniMax H3 via ComfyUI, dub with TTS voices, or export MP4/SRT.
---

# 镜流（Jingliu）AI 短剧操作

镜流是运行在用户本机的 AI 短剧工作台（ComfyUI + MiniMax H3 视频引擎 + FFmpeg 成片，
可选 Ollama + Qwen2.5 7B 本地编剧）。工作台以 HTTP API 监听本机
`http://127.0.0.1:7861`（默认端口，以实际安装为准），仅接受本机请求。

本技能通过 `scripts/jingliu.py`（纯标准库 CLI）驱动全部 API，兼容任何具备
本机 shell + Python 3 的 harness（WorkBuddy / Codex / zcode / 其他）。接入方式见
[references/clients.md](references/clients.md)。

## 基本约定

- 执行位置：仓库根目录可直接运行下列命令（有同名转发入口）；独立安装技能时，先进入包含本 SKILL.md 的技能目录，或用脚本绝对路径。无需依赖 Agent 的当前目录。
- 所有命令：`python scripts/jingliu.py <子命令> [参数]`，成功输出 JSON，失败返回非零退出码。
- 工作台不在默认地址时，用 `--base http://127.0.0.1:<端口>` 或环境变量 `JINGLIU_BASE`。
- 媒体路径均为项目内相对路径（如 `assets/xxx.png`、`renders/xxx.mp4`、`renders/xxx.srt`）。
- 长任务用 `wait --job-id` 轮询，进度打印到 stderr。只有 `done` 且退出码 0 才能进入下一阶段；失败为 3、取消为 4、超时为 124（不会取消后台任务）。连接或请求错误为 1，参数解析错误为 2。保留并读取 stdout 的任务 JSON；不要重复排队。
- 硬件与隐私：一切数据留在本机；不要把用户的素材、提示词、日志外传。

## 第 0 步：确认工作台可用

```bash
python scripts/jingliu.py status
```

- 返回 JSON：`comfy`（视频引擎就绪）、`ollama`（本地编剧）、`voices`（可用声线）、
  `h3_confirmed`（是否已确认模型许可）。
- 连接失败 → 工作台未启动。若用户机器从未部署，进入第 1 步；已部署则请用户双击
  「打开镜流」快捷方式，或参考 [references/deploy.md](references/deploy.md) 的启动命令。

## 第 1 步（可选）：检查与部署

仅当机器尚未安装镜流时执行。**必须先只读检查、向用户展示计划并获确认，再安装。**

```bash
# 在镜流仓库 checkout 目录中（只读检查，不改动系统）
python -B deploy/doctor.py --json --target "D:\JingliuRuntime"
python -B deploy/doctor.py --network          # 可选：检查全部下载来源
python -B deploy/installer.py plan --json --target "D:\JingliuRuntime" --region CN
# 用户确认计划编号后
python -B deploy/installer.py install --target "D:\JingliuRuntime" --region CN --approve <计划编号>
python -B deploy/installer.py verify --video --target "D:\JingliuRuntime"
python -B deploy/installer.py start   --target "D:\JingliuRuntime"
```

准入：Windows x64 + NVIDIA（8GB 显存起）、内存 16GB 起；新装视频工作流预留约 35 GiB
（加本地编剧约 45 GiB）。Doctor 支持 Windows/Linux/macOS 只读检测，但一键安装目前仅
验收过 Windows。计划内容（下载预算、磁盘、许可）必须逐项向用户确认。详见
[references/deploy.md](references/deploy.md)。

## 第 2 步：创建项目与分镜

```bash
python scripts/jingliu.py create --name "月台机器人" --aspect 9:16   # 或 16:9
```

两种方式得到分镜：

1. **本地编剧草案**（需 Ollama 已安装）：
   `draft --id <项目> --brief "故事想法或剧本" --count 5 --seconds 30` → `wait` →
   `apply-draft --id <项目>` 导入为正式分镜（同时导入建议素材与剧本）。
2. **手动逐镜**：`shot --id <项目> --action add`（最多 60 镜），然后
   `shot --id <项目> --action save --shot-id <镜头> --title ... --visual "画面描述" --prompt "动作提示词"
   --dialogue "小机器人：信号到了！" --seconds 4 --quality quick`

注意约束：`seconds` 0.5–12 秒；`quality` ∈ quick/normal/detail（首次用 quick 试拍）；
`prompt`/`visual` 至少填一个才能生成视频；台词每行「角色名：台词」，角色名需与素材名一致，
且台词要在镜头时长内读得完。

## 第 3 步：素材与首帧

```bash
python scripts/jingliu.py upload --id <项目> --file 角色图.png       # → {"file": "assets/xxx.png"}
python scripts/jingliu.py asset --id <项目> --name 小机器人 --kind character \
    --image assets/xxx.png --prompt "外观描述" --voice local-zh-female
python scripts/jingliu.py shot --id <项目> --action save --shot-id <镜头> --first assets/xxx.png
```

- 修改角色可只传 `--asset-id` 和要改的字段；未传字段保留原值，明确传空字符串才清除图片、提示词或声线。CLI 也兼容旧版工作台的整条覆盖接口。
- 没有 `--first`（首帧）的镜头不能生成视频。可用 `sketch --shot-id <镜头>` 让 H3
  抽帧生成概念草图作首帧，或为无图素材 `sketch --asset-id <素材>` 生成参考图。
- 尾帧（`--last`）可选，留空沿用首帧。固定角色造型请用确认过的参考图。

## 第 4 步：生成镜头

```bash
python scripts/jingliu.py video --id <项目> --shot-id <镜头> --steps 20   # 单镜
python scripts/jingliu.py video --id <项目>                               # 所有「有首帧且无成片」的镜头
python scripts/jingliu.py wait --job-id <任务ID> --timeout 7200
```

- `steps` 4–40，默认 20；验收/试拍可用 4 步加快出片。
- 首次生成要冷启动视频引擎（可能 1–2 分钟以上）并加载权重，请耐心等待，不要重复排队。
- 显存不足时：降为 quick 规格、缩短时长、关闭其他占显存程序后 `retry --job-id`。
- 动作提示词写法：主体 + 动作 + 环境 + 镜头运动，例如
  "Fixed camera, a small friendly robot standing on a quiet train platform, gently turns
  its head toward a warm signal light and blinks once. Subtle body movement, soft blue
  ambient light, consistent character appearance."
- 固定 `--seed` 便于在同一参考图上比较不同动作。

## 第 5 步：导出成片并下载

```bash
python scripts/jingliu.py export --id <项目> --size 720 --audio tts --voice local-zh-female
python scripts/jingliu.py wait --job-id <任务ID>
python scripts/jingliu.py project --id <项目>     # 从 exports 字段取 file（成片）与 subtitle（字幕）
python scripts/jingliu.py download --id <项目> --path renders/xxx.mp4 --out D:/output/成片.mp4
python scripts/jingliu.py download --id <项目> --path renders/xxx.srt --out D:/output/字幕.srt
```

- `--audio`：`source` 镜头原声 / `tts` 按台词合成配音 / `track` 项目音轨（需先
  `upload` 音频并 `edit-project --track`）/ `silent` 静音。
- 声线键名见 `status` 返回的 `voices`；离线默认 `local-zh-female`（Windows 系统语音，
  需已装中文语音包）；标注联网的 Edge 声线（zh-CN-XiaoxiaoNeural 等）需网络。
- 角色素材自带 `voice` 时优先于导出默认声线。
- 导出前每个镜头必须有 `clip`（已生成视频）或至少有 `first`。

## 常用诊断

```bash
python scripts/jingliu.py jobs --project <项目>     # 任务进度/错误
python scripts/jingliu.py retry  --job-id <失败任务>
python scripts/jingliu.py cancel --job-id <排队任务>
```

安装与运行日志位于安装目录：`install.log`、`verify.log`、`studio-data/comfy.log`、
`runtime.json`。排障时只在本机查看，外发前提醒用户先去除个人路径与素材信息。

## 完整 API 参考

见 [references/api.md](references/api.md)（含每个端点的字段、取值范围与限制）。
