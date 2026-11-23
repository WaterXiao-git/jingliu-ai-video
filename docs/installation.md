# 本机安装与验收

## 检查机器

如果已有 Python 3，在仓库目录执行以下任一命令。检测默认只读。添加 --network 会向清单里的来源发出 HEAD 请求。

    python -B deploy/doctor.py
    python -B deploy/doctor.py --json --target "E:\JingliuRuntime"

评级 A 可以按计划部署，B 需要采用配置建议或排除暂时的阻塞，C 需要补查或当前平台未纳入一键部署，D 表示机器低于当前工作流支持配置。看 can_install 决定是否继续。Apple Silicon 统一内存单独报告。GPU 显存、Windows 提交余量和磁盘都以当时的机器状态为准。

首版经过 Windows 11、RTX 4060 Laptop 8GB、16GB 级内存测试。8100 MiB 显存和 15 GiB 系统可见内存是对应标称硬件的首版准入线，低于该线的机器尚未验证。R580 为 CUDA 13.x 兼容性预检线，安装后还会测试 PyTorch CUDA。试拍用 320×576、22 帧、20 步。较长镜头和高分辨率有更高的资源需求。

| 配置 | 目标卷建议预留 |
|---|---|
| 新装视频工作流 | 35 GiB |
| 加装本地 Ollama 编剧 | 45 GiB |
| 复用已校验的 ComfyUI | 3 GiB 起，随作品数量增长 |

新装视频模型共 21,679,777,336 字节。安装计划另列 Python wheels、FFmpeg 等预算。下载、临时文件和作品可以留在所选磁盘。Windows 页面文件由系统设置管理。

## 模型来源与校验

0.1.4 按下表选择国内权重入口。五个视频权重按固定文件大小与 SHA-256 校验，已有校验通过的权重可复用。原始发布地址保存在清单的 upstream_url 字段中，供核对来源。

| 权重 | 当前下载入口 | 约下载大小 |
|---|---|---|
| H3 W4A8 主模型 | [魔搭 AI-ModelScope](https://modelscope.cn/models/AI-ModelScope/MiniMax-H3-w4a8) | 12.54 GB |
| Qwen3-VL 4B INT8 文字编码器 | [魔搭 Comfy-Org / Krea-2](https://modelscope.cn/models/Comfy-Org/Krea-2) | 4.86 GB |
| H3 视频 VAE INT8 | [魔搭 Kijai](https://modelscope.cn/models/Kijai/MiniMax-H3-experimental) | 3.17 GB |
| H3 音频 VAE FP32 | [魔搭 Comfy-Org](https://modelscope.cn/models/Comfy-Org/MiniMax-H3) | 0.61 GB |
| ClipProj 4B v3 MLP | [魔搭 HF 镜像仓库](https://modelscope.cn/models/hf/NicoLab28-ClipProj-MiniMax-H3) | 0.50 GB |
| 可选 Qwen2.5 7B Q4_K_M 编剧 | [魔搭 bartowski](https://modelscope.cn/models/bartowski/Qwen2.5-7B-Instruct-GGUF) | 4.68 GB |

六个权重均已从魔搭国内 CDN 完整下载并校验。新的文字编码器来自 Comfy-Org，文件与旧版 5.37 GB 编码器不同。清单保留旧文件的确切大小与 SHA-256 作为兼容项，旧用户无需覆盖已校验的文件。

ClipProj 的魔搭镜像采用 master 下载入口，安装器仍以清单中固定的大小和 SHA-256 校验文件。其余魔搭权重使用已核对的修订号。[完整清单](../deploy/deploy-spec.yaml)

可选编剧模型通过同一下载器获取 GGUF，校验后写入目标目录的 ollama-models/blobs 内容寻址存储，再用本地 Modelfile 注册为 qwen2.5:7b。Ollama 0.33.3 会在本机生成规范化 blob，可能另外占用约 4.7 GB，45 GiB 预算已留出这部分空间。原始已校验 GGUF 保留，便于重装与核对。对话模板随仓库提供，适配工作台的中文剧本和 JSON 输出。

本机 Ollama GPU 编剧探测长时间未返回，本版默认使用 CPU 编剧，生成视频继续使用 CUDA。希望测试其他编剧设备的开发者可在启动前设置 JINGLIU_OLLAMA_NUM_GPU（Ollama 的 num_gpu 参数），但 GPU 编剧路径不计入本版通过的验收范围。

可在仓库目录检查所有模型入口。检测只发出网络请求，模型权重在确认安装计划后下载。

    python -B deploy/doctor.py --network

硬件检测报告会列出 Python、PyPI、PyTorch、六个权重、FFmpeg、Ollama 的连通结果，并检查项目内的源码包是否存在。

## 程序与依赖的国内镜像

0.1.4 使用以下固定版本的国内下载源。HTTPS、文件大小与 SHA-256 用于验证完整下载；Python NuGet 包另已与官方 NuGet 记录中的 SHA-512 核对。

| 资源 | 当前来源 | 核对结果 |
|---|---|---|
| Python 3.11.9 x64 官方 NuGet 包 | [华为云 NuGet 镜像](https://mirrors.huaweicloud.com/repository/nuget/v3/index.json) | 完整校验，解压后可直接运行、创建 venv 和使用 pip |
| 85 个普通 Python 依赖 | [阿里云 PyPI 镜像](https://mirrors.aliyun.com/pypi/simple/) | 完整安装，包含全新环境所需的 setuptools 78.1.0 |
| torch、torchvision、torchaudio | [上海交大 CUDA 13.0 镜像](https://mirror.sjtu.edu.cn/pytorch-wheels/cu130/) | 完整安装固定版本的 Windows / Python 3.11 wheel，通过 pip check 与实际 CUDA 运算 |
| ComfyUI 与两个自定义节点 | 项目内 deploy/vendor 源码 ZIP | 原始提交及 SHA-256 固定，随 Gitee 项目下载，解压保留上游许可 |
| FFmpeg / ffprobe 8.0.1 | [魔搭 FFmpeg 副本](https://modelscope.cn/models/BeePlug/LittleHornet-FFmpeg8.0.1-CLI-Win-x64) | 可执行文件哈希匹配 Gyan 8.0.1，许可证与上游说明一起下载 |
| Ollama 0.33.3 Windows x64 | [CNB Ollama 同步仓库](https://cnb.cool/hex/ollama) | ZIP 完整 SHA-256 匹配 Ollama 官方发布记录 |

三个 PyTorch 包使用清单中的固定版本，普通依赖按 requirements-win-cu130.txt 中的版本安装。安装器分别从两个镜像安装 CUDA 包和普通依赖。上游索引记录在清单的 upstream_index 中，安装器使用表中的国内入口。

下载器直连清单中的域名，校验每次 HTTP 跳转。允许的分发域名为 gitee.com、modelscope.cn、mirrors.huaweicloud.com、mirrors.aliyun.com、mirror.sjtu.edu.cn、s3.jcloud.sjtu.edu.cn、cnb.cool 及其子域名。安装子进程关闭代理环境变量，避免依赖本机已配置的海外代理。上游地址保留作溯源信息，不参与默认安装下载。

## 安装到别的磁盘

在解压目录打开 PowerShell。把示例中的盘符和使用地区换成你的情况。

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1 -Mode Install -Target "E:\JingliuRuntime" -Region CN

如需同时配置 Ollama 与 Qwen2.5 7B，可加 -WithOllama。已有兼容的 Ollama 可以继续用 11434 端口上的服务。也可手动录入镜头和台词。

找不到 64 位 Python 3.11 时，启动脚本先做初检。初检通过后显示 Python 独立目录和下载大小，经同意解压官方 NuGet 包到目标目录的 python311。该方式不需要运行 MSI 安装器，也不修改系统 PATH。工作台依赖安装在独立虚拟环境中。该命令的执行策略仅应用于这次启动的 PowerShell 进程。

同一路径以后可用以下命令启动。默认路径可双击 **打开镜流.cmd**。

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1 -Mode Start -Target "E:\JingliuRuntime"

## 复用原来的 ComfyUI

复用目录应包含兼容的 ComfyUI、两个自定义节点、匹配的五个权重，以及 .venv。安装器校验依赖、真实 CUDA 运算及各权重 SHA-256。生成时使用镜流的数据目录保存临时图片、结果与队列记录。

    python -B deploy/installer.py plan --reuse-comfy "E:\ComfyUI" --region CN
    python -B deploy/installer.py install --reuse-comfy "E:\ComfyUI" --region CN
    python -B deploy/installer.py verify --video
    python -B deploy/installer.py start

安装前确认计划编号。Agent 非交互运行时，在用户确认后可以传入 --approve 与编号。计划和安装需使用同一套参数。

## 恢复与排错

- **磁盘空间不足**。选有空间的磁盘，用 --target 或 -Target 指定目录。旧目录可在确认无用后由你清理。
- **下载中断**。以相同目标目录和参数重试。支持 Range 的来源会从已保存的位置继续。
- **端口被占用**。工作台默认使用 7861，受管理的 ComfyUI 使用 8193，可选独立 Ollama 使用 11435。可在安装时用 --port / -Port 改工作台端口。
- **显存不足**。先保存其他应用的工作，释放显存，再选择试拍、短时长和较少的镜头。
- **日志**。目标目录的 install.log 记录依赖安装，verify.log 和 verify-comfy.log 记录自检，studio-data/comfy.log 记录生成。
- **验证**。verify 检查 CUDA、工作台、中文本地配音和字幕导出；安装了托管 Ollama 时还通过应用 API 生成真实剧本。verify --video 增加 H3 镜头生成。样片、SRT、检查帧与编剧结果保存在目标目录 acceptance 下。
- **本地配音缺少声线**。在 Windows 中安装对应的中文语音包后重试。默认女声和可选男声取决于系统中实际安装的语音；这类声音与 Edge 神经声线不同。使用联网声线会把台词发送给 Edge TTS，也可以上传已录制的音轨。

## 测试

    python -B -m unittest discover -s tests -v

28 项轻量测试覆盖硬件判断、中文声线条件、下载恢复、兼容文件、国内域名限制、启动器生命周期，以及 EXE 打包的隐私排除、确定性与资源完整性。跨平台结果以 CI 为准。

新版本的 `verify --video` 默认用 4 步短镜头做功能验收，不改变正式生成的默认 20 步。希望按 20 步验收时可加 `--video-steps 20`；PowerShell 对应 `-VideoSteps 20`。验收目录的 verification.json 记录实际步数，避免把功能小样误当作正式画质。

v0.1.4 已在同机独立目录完成国内资源完整下载、独立环境安装与真实出片，包含 CPU 编剧、分镜导入、H3、离线中文系统配音、字幕及 MP4 解码。[验收报告、样片与校验记录](acceptance/2026-11-23/index.md)。另一台实体机器及其他系统的完整视频部署仍需单独验收。

需要复核安装网络时，可把 deploy/acceptance_guard 目录加入本次启动进程的 PYTHONPATH，并将 JINGLIU_ACCEPTANCE_AUDIT 设为本机日志目录。它会记录并限制 Python 的 DNS 和 socket 连接。默认安装已给 pip 子进程启用这一守卫，日志写入目标目录 pip-domain-audit。普通创作启动不会自动启用该审计，以便用户主动选择标注为联网的声音服务。
