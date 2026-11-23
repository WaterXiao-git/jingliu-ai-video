<p align="center">
  <img src="docs/assets/jingliu-logo.png" alt="镜流 Jingliu Logo" width="144">
</p>

<h1 align="center">镜流 · Jingliu</h1>

<p align="center">在自己的电脑上，把剧本、角色参考图和分镜制作成 AI 短剧。</p>

<p align="center">
  <a href="https://gitee.com/xiao-ming-jun/jingliu-ai-video/tags"><img src="https://img.shields.io/badge/version-0.1.4-8062DE" alt="版本 0.1.4"></a>
  <a href="https://github.com/WaterXiao-git/jingliu-ai-video/actions/workflows/checks.yml"><img src="https://github.com/WaterXiao-git/jingliu-ai-video/actions/workflows/checks.yml/badge.svg" alt="GitHub 自动检查"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-6FE3B7" alt="应用源码 MIT 许可"></a>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#生成第一条视频">第一条视频</a> ·
  <a href="#制作自己的短剧">使用教程</a> ·
  <a href="#交给-agent-部署">Agent 部署</a> ·
  <a href="#常见问题">常见问题</a> ·
  <a href="https://gitee.com/xiao-ming-jun/jingliu-ai-video/issues">社区交流</a>
</p>

## 你可以用镜流做什么

镜流把本地 AI 视频工作流整理成可视化工作台。安装工具检查机器并准备运行环境，创作页面负责管理项目、生成镜头和导出成片。

| 功能 | 使用方式 |
| --- | --- |
| 检查电脑 | 查看显卡、显存、内存、驱动和目标磁盘空间，获得安装建议 |
| 自动部署 | 按确认的计划下载依赖和模型，校验文件，验证真实出片 |
| 剧本与拆镜 | 手动填写分镜，或通过可选的本地 Ollama 编剧模型生成草案 |
| 角色与场景 | 保存参考图、角色描述和配音声线，供不同镜头复用 |
| 分镜制作 | 设置首尾帧、动作提示词、时长与生成规格，预览和重试镜头 |
| 生成队列 | 查看任务进度、错误和生成历史，逐个处理镜头 |
| 成片与导出 | 拼接镜头，添加配音和字幕，导出 MP4 与 SRT |
| 新手引导 | 在页面中跟随提示，用内置「月台机器人」项目完成练习 |

视频引擎使用 **ComfyUI + MiniMax H3**，成片处理使用 **FFmpeg**。本地编剧使用可选的 **Ollama + Qwen2.5 7B**。中文离线配音使用 Windows 已安装的中文系统声线，另保留联网 Edge TTS 声线供选择。具体版本与文件校验值随仓库固定。[部署清单](deploy/deploy-spec.yaml)

本地编剧默认使用 CPU，给视频模型留出显存。首次编剧需加载模型，请等待队列完成。

## 安装前先看配置

当前一键安装面向 **Windows x64 + NVIDIA 显卡**。已完成真实生成验证的机器为 **RTX 4060 Laptop 8GB + 16GB 内存**。

| 项目 | 当前准入与空间预算 |
| --- | --- |
| 系统 | Windows x64，已在 Windows 11 验证 |
| 显卡 | NVIDIA CUDA，标称 8GB 显存起，检测线为 8100 MiB |
| 内存 | 标称 16GB 起，系统可见内存检测线为 15 GiB |
| 驱动 | 支持 CUDA 13.x，安装器按 R580 及以上预检，并测试实际 CUDA 运算 |
| 新装视频工作流 | 目标磁盘建议预留 **35 GiB** |
| 同时安装本地编剧 | 目标磁盘建议预留 **45 GiB** |
| 复用兼容 ComfyUI | 建议 **3 GiB 起**，另为素材、镜头和成片留空间 |
| 网络 | 首次从国内来源下载依赖和模型，五个视频权重合计约 **21.7 GB** |
| 离线中文配音 | Windows 需已安装对应的中文系统语音包，默认使用中文女声 |

较长镜头和更高画质会增加显存、内存与生成时间。首次运行建议用 **试拍档、1–2 秒、单个镜头**。

Doctor 支持在 Windows、Linux 和 macOS 上做只读检测。Linux、macOS 的一键部署仍待实机验收。配置不足或平台暂未支持时，检测报告会给出其他生成平台的选项。[检测规则与安装说明](docs/installation.md)

## 模型下载来源

五个视频权重和可选的 Qwen2.5 7B 编剧权重均从 **魔搭 ModelScope** 下载。安装器校验文件大小和 SHA-256，并复用校验通过的已有文件。

安装下载只允许清单中的国内分发域名，并检查每次跳转。出现境外跳转时会停止并提示。新的文字编码器使用 Comfy-Org 在魔搭发布的转换版本，原有已校验的编码器仍可复用。[逐项来源与验证方式](docs/installation.md#模型来源与校验)

Python 3.11.9 使用华为云镜像中的官方 NuGet 免安装包，普通 Python 依赖使用阿里云镜像，CUDA 13.0 版 PyTorch 使用上海交大镜像。固定版本的 ComfyUI 与插件源码随 Gitee 项目包提供，FFmpeg 从魔搭下载，Ollama 从 CNB 下载。[安装资源来源](docs/installation.md#程序与依赖的国内镜像)

## 快速开始

### 下载项目

从 [Gitee 主仓库](https://gitee.com/xiao-ming-jun/jingliu-ai-video) 的「克隆/下载」下载 ZIP，完整解压到有足够空间的磁盘。也可以在 PowerShell 中执行以下命令。

~~~powershell
git clone https://gitee.com/xiao-ming-jun/jingliu-ai-video.git
cd jingliu-ai-video
~~~

[GitHub 镜像](https://github.com/WaterXiao-git/jingliu-ai-video) 提供同一版本的代码与自动检查记录。

### 检查并安装

1. 双击项目根目录的 **打开镜流.cmd**。
2. 选择 **检查这台电脑**，查看检测结果和空间建议。
3. 检查通过后，再次双击启动文件，选择 **检查并安装**，按提示填写实际使用地区，阅读模型许可。
4. 查看安装目录、下载预算和计划编号，确认后开始安装。需要自动编剧时，选择同时安装 Ollama。
5. 等待依赖安装、模型校验和短镜头验证完成，脚本会打开工作台。

默认运行数据保存在项目下的 `.runtime`。缺少兼容 Python 时，脚本会提示下载官方 Python 3.11 到目标目录。首次安装时间取决于下载速度和机器性能。

工作台默认地址为 [http://127.0.0.1:7861/](http://127.0.0.1:7861/)。保持启动窗口运行，以便页面连接本地服务。后续使用时再次双击 **打开镜流.cmd**，会直接启动已配置的工作台。

<details>
<summary><strong>系统盘空间紧张，安装到其他磁盘</strong></summary>

在项目目录打开 PowerShell，把目标路径与地区代码替换成自己的实际情况。下面的 `CN` 表示中国。

~~~powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1 -Mode Check -Target "E:\JingliuRuntime"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1 -Mode Install -Target "E:\JingliuRuntime" -Region CN
~~~

同时安装本地编剧时，在安装命令末尾添加 `-WithOllama`。此后使用相同目标路径启动。

~~~powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1 -Mode Start -Target "E:\JingliuRuntime"
~~~

</details>

<details>
<summary><strong>已经有 ComfyUI，希望复用模型和环境</strong></summary>

复用目录需包含兼容的 ComfyUI、`.venv`、所需自定义节点和五个匹配权重。安装器会检查依赖、真实 CUDA 运算和模型 SHA-256。

~~~powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1 -Mode Install -ReuseComfy "E:\ComfyUI" -Region CN
~~~

把目录和地区替换成实际值。已有文件是否可复用，以安装器的校验结果为准。[详细复用流程](docs/installation.md#复用原来的-comfyui)

</details>

## 生成第一条视频

用内置示例走完一次流程，再开始正式项目。

1. **导入练习项目**

   在首页点 **导入月台机器人示例**。也可以点右上角 **新手引导**，跟随页面提示操作。
2. **检查分镜**

   打开 **分镜制作**，确认示例已有首帧和动作提示词。首次保持短时长与试拍规格，点 **保存修改**。
3. **生成镜头**

   点 **生成这个镜头**，进入 **生成队列** 查看进度。模型首次加载需要等待，完成后回到分镜页播放片段。
4. **选择声音与字幕**

   打开 **成片与导出**，首次可以选择 **保留镜头原声** 或 **静音**，按需要开启字幕。
5. **导出并下载**

   选择 720p，启动导出，完成后下载 MP4。包含台词时，还可下载 SRT 字幕。

示例附带参考图和分镜参数。执行镜头生成后，可以预览真实的视频片段。生成任务按队列依次执行。

## 制作自己的短剧

### 写剧本并拆成镜头

在首页点 **新建项目**，选择竖屏 9∶16 或横屏 16∶9。在 **剧本与拆镜** 填写故事想法或已有剧本。

- 已安装本地编剧模型时，选择模型生成草案，检查剧情、角色与时长，再导入分镜。
- 手动制作时，在 **分镜制作** 新增镜头，分别填写画面、台词、提示词和时长。

一个镜头尽量表达一个明确动作。先做短镜头，确认角色外观与画面风格，再逐步增加内容。

### 准备角色与首尾帧

在 **角色与场景** 添加素材，上传 PNG、JPG 或 WebP 参考图，填写角色名称、外观描述和配音声线。

进入 **分镜制作**，把选定素材用作首帧。希望镜头有明确结束构图时，可以设置尾帧。尾帧留空时沿用首帧。需要固定人物造型时，使用确认过的角色参考图。

页面也提供 **生成草图**，通过 H3 短视频抽帧获得概念图，适合先试构图和方向。

### 描述画面如何运动

动作提示词包含主体、动作、环境与镜头运动。可以从下面这个简短例子开始。

~~~text
Fixed camera, a small friendly robot standing on a quiet train platform,
gently turns its head toward a warm signal light and blinks once.
Subtle body movement, soft blue ambient light, consistent character appearance.
~~~

在同一参考图上逐次调整动作，固定随机种子便于比较结果。每次修改后先保存，再生成。

| 生成规格 | 竖屏源尺寸 | 适用场景 |
| --- | --- | --- |
| 试拍 | 320 × 576 | 确认构图、动作和流程 |
| 标准 | 480 × 864 | 继续完善镜头 |
| 细节 | 768 × 1344 | 资源允许时提高细节 |

横屏规格交换宽高。成片导出支持 720p、1080p，并按项目画幅缩放裁切。源镜头的细节由生成规格决定。

### 配台词和声线

在镜头台词中按行填写角色名与台词，角色名和素材名称保持一致。

~~~text
小机器人：信号到了！
站长：我们出发吧。
~~~

在 **角色与场景** 为同名角色选择声线，在 **成片与导出** 选择 **按台词合成配音**。角色声线优先，其他台词使用导出时选定的默认声线。可选少年男声、青年女声等预设。

台词需要能在镜头时长内读完。配音提示语速过快时，缩短台词或增加镜头时长，然后重新导出。默认的「本地中文女声」使用系统语音，可离线运行，音色取决于已安装的 Windows 中文声线。中文男声需要对应的系统语音包；缺少时会提示。标注「联网」的少年、青年等 Edge 声线需要网络。角色素材中设置的声线优先。

### 拼接并导出

确认时间线中的镜头和顺序，进入 **成片与导出**。

| 声音来源 | 适用方式 |
| --- | --- |
| 项目音轨 | 上传已经准备好的配音或完整音轨 |
| 按台词合成配音 | 按角色台词生成声音 |
| 保留镜头原声 | 使用生成或导入片段自带的声音 |
| 静音 | 导出无声视频 |

选择导出分辨率和字幕选项，完成后下载 MP4 与可用的 SRT。需要重做某个镜头时，可以重新生成，或在历史片段中选择已有结果。

## 交给 Agent 部署

将仓库链接和下面的任务发给具备本机终端权限的 Agent。

> 请拉取 https://gitee.com/xiao-ming-jun/jingliu-ai-video ，阅读仓库中的 ai-video-deployer Skill。先做只读硬件与磁盘检查，并用 Doctor 的 --network 逐项检查模型来源。给出安装位置、下载预算、可复用环境和配置差距。等我确认计划后，执行安装和真实视频验证，最后打开工作台并教我完成示例项目。

[Agent Skill](.agents/skills/ai-video-deployer/SKILL.md) 覆盖检测、安装计划、确认、部署与验证。[客户端接入说明](.agents/skills/ai-video-deployer/references/clients.md) 包含 Codex、WorkBuddy 与 DeepSeek Harness 的接入方式，其中后两者仍待实机验收。

<details>
<summary><strong>开发者与 Agent 常用命令</strong></summary>

在仓库目录中使用 Python 执行。安装与启动使用 64 位 Python 3.11，命令默认采用 `.runtime` 作为目标目录。

~~~powershell
# 只读检查
python -B deploy/doctor.py

# 输出结构化结果，检查指定目标磁盘
python -B deploy/doctor.py --json --target "E:\JingliuRuntime"

# 检查依赖与全部模型下载入口
python -B deploy/doctor.py --network

# 生成安装计划，地区代码按实际情况填写
python -B deploy/installer.py plan --region CN

# 确认计划后安装
python -B deploy/installer.py install --region CN

# 实际生成短视频并验证
python -B deploy/installer.py verify --video

# 启动工作台
python -B deploy/installer.py start

# 运行轻量测试
python -B -m unittest discover -s tests -v
~~~

安装器命令指定自定义目标时，在计划、安装、验证、启动各步保持相同的 `--target`。非交互安装在用户确认计划后使用 `--approve` 和对应计划编号。[完整参数与部署说明](docs/installation.md)

</details>

## 常见问题

### 检查结果是 B，可以安装吗

B 可能代表需要使用低资源配置，也可能有暂时的空间或资源阻塞。根据报告中的具体建议和 `can_install` 决定是否继续。C 需要补查或等待平台适配，D 表示低于当前支持配置。

### 磁盘空间不够怎么办

将运行目录指定到有空间的磁盘，或复用已校验的 ComfyUI。新装视频模型约 21.7 GB，此外还需要运行环境、下载临时空间和作品空间。每次生成的片段会继续占用磁盘。

### 下载中断了，要重新开始吗

使用相同目标目录和安装参数重试。来源支持 Range 时会续传已保存的数据，下载完成后进行校验。

### 生成时报显存不足怎么办

保存其他应用的工作并释放显存，把镜头调整为试拍档和较短时长，再到队列重试。生成耗时受显卡、分辨率、帧数和当前系统资源影响。

### 浏览器打不开工作台怎么办

确认启动窗口仍在运行，并查看终端输出的实际地址。默认端口为 7861。端口冲突时，可以在安装命令中通过 `-Port` 指定其他工作台端口，再按配置启动。

### 如何找项目和日志

默认目标目录是 `.runtime`。使用自定义安装目录时，在该目录查找以下文件。

| 路径 | 内容 |
| --- | --- |
| `runtime.json` | 运行配置和路径 |
| `studio-data/projects/` | 项目数据、上传素材和导出结果 |
| `install.log` | 依赖安装记录 |
| `verify.log`、`verify-comfy.log` | 安装后的验证记录 |
| `studio-data/comfy.log` | 视频引擎运行记录 |

反馈问题时附上操作步骤、Doctor 结果和相关日志片段，并先检查其中的个人路径和素材信息。

### 现在验证到哪一步了

已在上述 Windows NVIDIA 机器上验证复用环境部署、从 GitHub 源码 ZIP 启动、H3 镜头生成和成片导出。CI 覆盖 Windows、Linux、macOS 的轻量检测与恢复逻辑测试。另一台干净电脑上的全新模型下载及首次出片仍待验收。[验收说明](docs/installation.md#测试)

## 社区与作品分享

在 **成片与导出** 中预览并下载分享卡，再自行发布到 Gitee Issues。分享卡可以包含缩略图与公开作品链接，提示词需要单独勾选。

- [Gitee Issues](https://gitee.com/xiao-ming-jun/jingliu-ai-video/issues) 用于答疑、问题反馈、功能建议与作品分享。分享作品时可在标题中注明「作品分享」。
- [GitHub Discussions](https://github.com/WaterXiao-git/jingliu-ai-video/discussions) 也可交流经验和作品。
- [项目展示页](https://waterxiao-git.github.io/jingliu-ai-video/) 提供项目入口与部署信息。
- [社区说明与投稿接口](docs/community.md) 记录分享卡格式及后续托管方案。

当前分享流程由用户主动导出、手动投稿。后续在线社区可基于预留的分享卡格式接入托管服务。

## 数据与许可

硬件检测、参考图、项目和视频生成由本机处理。首次安装与模型下载需要网络，启用 Edge TTS 时会把选定台词发送给语音服务。工作台监听本机地址。

镜流应用源码采用 MIT 许可。MiniMax H3、其他依赖、参考素材及生成输出的使用需分别遵守对应条款，安装时请按实际地区核对 H3 社区许可与可接受使用政策。[应用许可](LICENSE) · [H3 许可全文](docs/MINIMAX-H3-LICENSE.txt) · [第三方组件](NOTICE.md)
