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

新装模型共 22,195,387,552 字节。安装计划另列 Python wheels、FFmpeg 等预算。下载、临时文件和作品可以留在所选磁盘。Windows 页面文件由系统设置管理。

## 模型来源与校验

0.1.2 起，安装器按下表选择权重入口。五个视频权重按已验证的文件大小与 SHA-256 校验，已有校验通过的权重可复用。原始发布地址保存在清单的 upstream_url 字段中，供核对来源。

| 权重 | 当前下载入口 | 约下载大小 |
|---|---|---|
| H3 W4A8 主模型 | [魔搭 AI-ModelScope](https://modelscope.cn/models/AI-ModelScope/MiniMax-H3-w4a8) | 12.54 GB |
| Qwen3-VL 4B INT8 文字编码器 | [HF-Mirror / Stick9190](https://hf-mirror.com/Stick9190/qwen3vl_4b_int8_convrot) | 5.37 GB |
| H3 视频 VAE INT8 | [魔搭 Kijai](https://modelscope.cn/models/Kijai/MiniMax-H3-experimental) | 3.17 GB |
| H3 音频 VAE FP32 | [魔搭 Comfy-Org](https://modelscope.cn/models/Comfy-Org/MiniMax-H3) | 0.61 GB |
| ClipProj 4B v3 MLP | [魔搭 HF 镜像仓库](https://modelscope.cn/models/hf/NicoLab28-ClipProj-MiniMax-H3) | 0.50 GB |
| 可选 Qwen2.5 7B Q4_K_M 编剧 | [魔搭 bartowski](https://modelscope.cn/models/bartowski/Qwen2.5-7B-Instruct-GGUF) | 4.68 GB |

魔搭五项下载请求已通过本机免代理分段读取，实际文件来自 modelscope.cn 的国内 CDN。文字编码器暂未找到同哈希的魔搭副本，使用 HF-Mirror 的固定版本入口，其文件请求会跳转到 Hugging Face CDN。本机免代理分段读取已通过，其他地区与运营商仍需自行检测。HTTPS 下载与完整 SHA-256 校验用于验证文件内容，下载失败可按原参数重试。

ClipProj 的魔搭镜像采用 master 下载入口，安装器仍以清单中固定的大小和 SHA-256 校验文件。其余魔搭权重使用已核对的修订号。[完整清单](../deploy/deploy-spec.yaml)

可选编剧模型通过同一下载器获取 GGUF，校验后写入目标目录的 ollama-models/blobs 内容寻址存储，再用本地 Modelfile 注册为 qwen2.5:7b。注册时复用该 blob。对话模板随仓库提供，适配工作台的中文剧本和 JSON 输出。

可在仓库目录检查所有模型入口。检测只发出网络请求，模型权重在确认安装计划后下载。

    python -B deploy/doctor.py --network

硬件检测报告会列出 PyPI、GitHub、PyTorch 和六个权重入口的连通结果。

## 程序与依赖的国内镜像

0.1.3 起，安装器使用以下固定版本的国内下载源。

| 资源 | 当前来源 | 核对结果 |
|---|---|---|
| Python 3.11.9 x64 安装包 | [华为云 Python 镜像](https://mirrors.huaweicloud.com/python/3.11.9/) | 完整读取并校验，大小与 SHA-256 均匹配原清单 |
| 84 个普通 Python 依赖 | [阿里云 PyPI 镜像](https://mirrors.aliyun.com/pypi/simple/) | 固定版本的 Windows / Python 3.11 wheel 均已核对，索引中的 SHA-256 匹配官方记录 |
| torch、torchvision、torchaudio | [上海交大 CUDA 13.0 镜像](https://mirror.sjtu.edu.cn/pytorch-wheels/cu130/) | 已找到清单锁定版本的 Windows / Python 3.11 wheel，分段读取返回有效 ZIP 文件，实际存储位于交大域名 |

三个 PyTorch 包使用清单中的固定版本，普通依赖按 requirements-win-cu130.txt 中的版本安装。安装器分别从两个镜像安装 CUDA 包和普通依赖。上游索引记录在清单的 upstream_index 中，安装器使用表中的国内入口。

ComfyUI 与两个插件的源码包、FFmpeg 和 Ollama 程序包目前使用 GitHub 发布源。源码可按固定提交镜像到 Gitee，程序包也可在核对版本和校验值后分发到国内托管服务。CNB 提供 Ollama 国内镜像，本次抽样确认 v0.33.3 的 Windows ZIP 可从 asset.cnb.cool 读取，当前锁定的 v0.40.16 尚未完成同版镜像验证。

因此，本版已接入三类程序与依赖的国内镜像，全新安装仍需访问其余发布源。版本等效性、文件校验与实际连通性需要逐项核对。

## 安装到别的磁盘

在解压目录打开 PowerShell。把示例中的盘符和使用地区换成你的情况。

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup.ps1 -Mode Install -Target "E:\JingliuRuntime" -Region CN

如需同时配置 Ollama 与 Qwen2.5 7B，可加 -WithOllama。已有兼容的 Ollama 可以继续用 11434 端口上的服务。也可手动录入镜头和台词。

找不到 64 位 Python 3.11 时，启动脚本先做初检。初检通过后显示官方 Python 安装位置和下载大小，经同意安装到目标目录。工作台依赖安装在独立虚拟环境中。该命令的执行策略仅应用于这次启动的 PowerShell 进程。

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
- **验证**。verify 检查 CUDA、工作台和定帧导出，verify --video 还会真实生成 H3 镜头。AI 配音遇到网络错误时，可选源音轨、上传音轨或静音。

## 测试

    python -B -m unittest discover -s tests -v

测试在不下载模型的条件下覆盖硬件判断和下载恢复。全新环境的完整下载和首次出片，应在另一台干净的 Windows NVIDIA 电脑上验收。
