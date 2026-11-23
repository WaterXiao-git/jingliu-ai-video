# 第三方组件说明

MiniMax H3 is licensed under the MiniMax H3 Community License Agreement.

根目录 LICENSE 适用于本工作台和部署工具的自有代码与文档。独立依赖、模型和上游许可文件遵循各自条款。

- 适用地域和使用限制请见随包提供的 [MiniMax H3 社区许可](docs/MINIMAX-H3-LICENSE.txt)。安装时需声明实际使用地区并确认具备使用权。模型、衍生权重和生成输出适用各自相关条款。
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI) 和 [Spectrum](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3) 是独立安装的 GPL-3.0 组件。[ClipProj](https://github.com/nicolab28/ComfyUI-ClipProj) 为 MIT。
- deploy/vendor 内提供上述三个组件的完整上游源码 ZIP，原始许可证包含在各源码包内。版本、SHA-256 和上游地址记录在部署清单中。它们通过项目包分发并独立安装。
- 可选的 [Ollama](https://github.com/ollama/ollama) 与 Qwen2.5 7B 用于本地剧本拆分。GGUF 采用 [bartowski 发布的 Q4_K_M 量化版本](https://modelscope.cn/models/bartowski/Qwen2.5-7B-Instruct-GGUF)，遵循 Qwen2.5 的 Apache-2.0 许可。另见 FFmpeg [许可信息](https://ffmpeg.org/legal.html) 与 [Windows 构建列表](https://www.gyan.dev/ffmpeg/builds/)。
- 仓库内的「月台机器人」PNG 是可随镜流分发的静态示例图。生成的视频由用户按所选模型和素材条款使用。
