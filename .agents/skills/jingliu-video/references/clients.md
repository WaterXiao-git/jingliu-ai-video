# 各 harness 接入方式（clients）

本技能是「标准 SKILL.md + 本地 CLI 脚本」结构，不依赖任何单一客户端的专有机制。
任何具备「本机 shell + Python 3 + 文件系统」能力的 harness 均可使用。

## 通用原则

仓库根目录的 `scripts/jingliu.py` 是转发入口。独立安装技能后，先 `cd <技能目录>`，或使用 `python <技能目录绝对路径>/scripts/jingliu.py ...`，不要求工作台源码也在当前目录。发布页提供独立的 `Jingliu-Agent-Skill-<版本>.zip`；Windows 便携包也附带同一份 `jingliu-video/`。

`wait` 成功为 0，任务失败为 3，取消为 4，超时为 124；stdout 保留任务 JSON。必须检查任务状态再继续导出。

下列各客户端目录是接入约定；仍需按末尾清单在目标客户端实测技能发现和调用，不能仅凭 CLI 测试宣称所有客户端自动触发已验收。

- 技能目录整体可拷贝/移动，唯一硬依赖是 `scripts/jingliu.py` 与 Python 3（≥3.8，纯标准库）。
- CLI 与工作台同机运行（API 仅监听 127.0.0.1）。远程/沙箱环境无法直连用户本机工作台，
  此时应把命令交给用户在本机执行，或由用户选择暴露方式。
- 若 harness 支持技能发现，按下列方式安装一份即可；若不支持，直接在提示词中指明
  本技能 `SKILL.md` 的绝对路径即可。

## WorkBuddy（本机）

用户级安装（推荐，全会话可用）：

```
C:\Users\<用户名>\.workbuddy\skills\jingliu-video\
├── SKILL.md
├── scripts\jingliu.py
└── references\{api.md, deploy.md, clients.md}
```

项目级安装：放入 `{workspace}\.workbuddy\skills\jingliu-video\`。
安装后在对话中说「用 jingliu-video 技能…」即可触发；WorkBuddy 会在任务匹配
description 时自动加载。

## Codex

Codex 会发现打开目录下的 `.agents/skills/*/SKILL.md`。把本技能放到项目根：

```
<项目根>\.agents\skills\jingliu-video\SKILL.md
```

打开该目录后用 `$jingliu-video` 显式调用，或在任务描述中提及镜流让它自动匹配。
镜流仓库自身已带 `.agents/skills/ai-video-deployer`（部署专用），本技能与之互补：
部署用官方 deployer，部署后的日常操作用本技能。

## zcode 及其他 harness

- 支持 `.agents/skills` 约定的：同 Codex 放法。
- 支持自定义技能目录的：把整个 `jingliu-video/` 目录放进其技能搜索路径。
- 都不支持时：把 `SKILL.md` 内容（或路径）附进系统提示词/项目说明，
  约定「涉及镜流操作时先读 SKILL.md，再运行 `python scripts/jingliu.py ...`」。

## 冒烟验收清单（接入新 harness 后跑一遍）

```bash
python scripts/jingliu.py status                       # ① 工作台可达
python scripts/jingliu.py create --name "接入测试" --aspect 9:16   # ② 建项目
python scripts/jingliu.py sample                       # ③ 导入示例（可选）
python scripts/jingliu.py shot --id <项目> --action add # ④ 加镜头
python scripts/jingliu.py jobs                          # ⑤ 读任务
```

①~⑤ 全部返回合法 JSON 且退出码 0 即视为接入成功。涉及真实视频生成的验收
（`video` → `wait` → `export` → `download`）须在满足硬件要求的机器上进行。
