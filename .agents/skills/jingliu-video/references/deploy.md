# 镜流部署与启动（deploy 参考）

本技能只负责「调用已部署的镜流」；首次安装请克隆仓库后使用其自带部署脚本，
或使用仓库自带的部署类 Agent Skill（`.agents/skills/ai-video-deployer/SKILL.md`）。

## 仓库获取

```powershell
git clone https://gitee.com/xiao-ming-jun/jingliu-ai-video.git   # 国内主仓库
# GitHub 镜像：https://github.com/WaterXiao-git/jingliu-ai-video
cd jingliu-ai-video
```

另有 Windows EXE（预览版）：Gitee Releases 下载 `Jingliu.exe`，双击即可，
无需 Git/Node.js，适合少接触命令行的用户。

## 部署命令（在仓库目录，64 位 Python 3.11）

```bash
# 只读检查（不改系统；Windows/Linux/macOS 均可）
python -B deploy/doctor.py --json --target "D:\JingliuRuntime"
python -B deploy/doctor.py --network          # 检查依赖与全部模型下载入口

# 生成安装计划 → 用户确认 → 安装 → 真实出片验证 → 启动
python -B deploy/installer.py plan   --json --target "D:\JingliuRuntime" --region CN
python -B deploy/installer.py install       --target "D:\JingliuRuntime" --region CN --approve <计划编号>
python -B deploy/installer.py verify --video --target "D:\JingliuRuntime"
python -B deploy/installer.py start         --target "D:\JingliuRuntime"
```

可选参数：

- `--reuse-comfy "E:\ComfyUI"`：复用已有兼容 ComfyUI（需含 .venv、自定义节点与五个匹配权重，安装器做 SHA-256 校验）。
- `--with-ollama`：同时安装本地编剧（Ollama + Qwen2.5 7B，多占约 10 GiB）。
- Windows 下也可用 `deploy/setup.ps1 -Mode Check|Install|Start -Target ... -Region CN`。

**Python 3.11 要求**：doctor/plan 可用任意 Python 3 运行，但 `install` 必须用 64 位
Python 3.11 启动安装器。系统没有 3.11 时的官方引导方式（setup.ps1 自动执行，手动等价步骤）：

1. 从华为云镜像下载官方 NuGet 包（约 18 MB，与 `deploy-spec.yaml` 的
   `python_bootstrap` 一致）：
   `https://mirrors.huaweicloud.com/artifactory/api/nuget/v3/nuget-remote/python/3.11.9/python.3.11.9.nupkg`
2. 校验 SHA-256 = `9283876d58c017e0e846f95b490da3bca0fc0a6ee1134b2870677cfb7eec3c67`。
3. 解压取 `tools/` 作为 `<目标目录>\python311\`，用其中的 `python.exe -B deploy/installer.py ...`
   执行后续 plan/install/verify/start。

## 硬件与空间准入

| 项 | 要求 |
| --- | --- |
| 系统 | Windows x64（Win11 已验证）；Linux/macOS 仅支持只读检测 |
| 显卡 | NVIDIA CUDA，标称 8GB 显存起（检测线 8100 MiB） |
| 内存 | 标称 16GB 起（检测线 15 GiB） |
| 驱动 | R580 及以上，支持 CUDA 13.x，安装器实测 CUDA 运算 |
| 磁盘 | 新装视频工作流约 35 GiB；加本地编剧约 45 GiB；复用 ComfyUI 3 GiB 起 |
| 网络 | 首次从国内源（ModelScope/华为云/阿里云/上交/CNB）下载，视频权重约 21.7 GB |

Doctor 结果分级：A 可装；B 需按报告建议（低配或暂时阻塞）；C 需补查/等平台适配；D 低于支持配置。
配置不足时参考 `deploy/platforms.yaml` 给用户推荐其他生成平台。

## 日常启动

- 桌面快捷方式「打开镜流」/「关闭镜流」（安装后自动创建）。
- 或仓库根目录双击 `打开镜流.cmd`。
- 启动后工作台地址默认 `http://127.0.0.1:7861/`，端口冲突时安装时用 `-Port` 指定，
  之后 CLI 调用加 `--base http://127.0.0.1:<端口>`。

## 目录与日志（在安装目标目录下）

| 路径 | 内容 |
| --- | --- |
| `runtime.json` | 运行配置和路径（确认实际端口/目录先看这里） |
| `studio-data/projects/` | 项目数据、上传素材、导出结果 |
| `install.log` / `verify.log` / `verify-comfy.log` | 安装与验证记录 |
| `studio-data/comfy.log` | 视频引擎运行记录 |

反馈问题时附上 Doctor 结果与相关日志片段，并先检查个人路径与素材信息。

## 安装交互纪律（Agent 必须遵守）

1. 先只读检查（doctor + plan + 可选 --network），**不得**未经确认直接 install。
2. 向用户逐项展示：安装目录、下载预算（约 21.7 GB 权重）、可复用环境、配置差距、
   模型许可（MiniMax H3 社区许可与可接受使用政策，按用户实际地区核对）。
3. 用户明确确认计划编号后才执行 install；下载中断用相同参数重试可续传。
4. 安装完成必须跑 `verify --video` 确认真实出片，再启动工作台。
5. 设备细节、凭据、提示词与媒体留在本机，除非用户明确要求分享。
