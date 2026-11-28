镜流 · Windows EXE 启动中心（预览版）

1. 完整解压这个 ZIP，双击 Jingliu.exe。
2. 已有部署：程序自动寻找并打开工作台，沿用原有模型与项目。自定义位置未找到时在“高级设置”选择 runtime.json。
3. 首次使用：自动选择空间充足的磁盘、附近已有环境及空闲端口，并自动检测电脑。无需填写技术参数。缺少 Python 时会先准备约 18 MB 官方 Python；此步不会下载视频模型。
4. 阅读包内模型许可，核对实际地区、空间预算和安装计划，勾选同意后安装。
5. 点“一键安装并打开”。安装后会做 4 步短镜头功能验收，包含本地中文配音、字幕和导出；正式生成仍默认 20 步。完成后自动打开工作台。
6. 工作台在默认浏览器中打开。关闭网页或启动中心不会停止生成；结束使用时点击“关闭后台”。

系统：Windows 10 / 11 x64，.NET Framework 4.8 或更新的 4.x。
视频生成：NVIDIA 8GB 显存、16GB 内存及兼容驱动起；实际以本机检测为准。低配置运行可能较慢。
新装建议预留 35 GiB，含编剧预留 45 GiB。模型从国内来源下载，不包含在 EXE 中。
中文离线配音依赖 Windows 已安装的中文语音包。

EXE 运行不需要预先安装 Git 或 Node.js。程序缓存和启动中心日志保存在 %LOCALAPPDATA%\Jingliu；模型和项目在你选择的运行目录。
这是未签名预览版，另一台实体机器的完整安装仍需验收。没有修改系统安全设置。
Jingliu.exe.sha256 用于核对 EXE 的 SHA-256。完整说明见启动中心的“帮助 / 在线方案”。

主仓库：https://gitee.com/xiao-ming-jun/jingliu-ai-video
GitHub 镜像：https://github.com/WaterXiao-git/jingliu-ai-video

便携包附带 jingliu-video 文件夹，可作为独立技能安装到本地 Agent；进入技能目录运行 python scripts/jingliu.py status，或使用脚本绝对路径。wait 的失败/取消/超时退出码分别为 3/4/124。
