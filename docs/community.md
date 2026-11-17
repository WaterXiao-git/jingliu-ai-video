# 作品分享与社区

在「成片与导出」点「导出分享卡」。选镜头，可填写已公开的 HTTPS 作品链接。你能看到即将下载的 JSON 和缩略图。只有勾选「将所选镜头提示词加入分享卡」才会复制提示词。修改内容后需要重新预览。

在你确认可以公开后，把作品介绍、图片和链接自行提交到 GitHub Discussions。请核对模型及素材的使用范围。反馈安装问题时，可复制 Doctor 结果，并在提交前检查内容。

## 无服务器起步

GitHub Discussions 用于答疑、作品征集与反馈。GitHub Pages 可以展示文档、教程和维护者选中的作品条目。展示页只存封面和公开链接，视频由创作者选择的平台提供播放。发布前审查作品来源和可展示地区。

## 投稿接口

本机可导出的 JSON 使用 jingliu.share.v1。字段为 schema、title、shot、aspect、可选 public_url、可选 prompt 和可选 thumbnail。缩略图另存为 JPEG，thumbnail.file 给出文件名，thumbnail.source 为 video_frame 或 reference_frame。公开页面只读已审核数据。

以后启用托管服务时，可由 Workers 实现 POST /v1/submissions、GET /v1/gallery 和 DELETE /v1/submissions/{id}。写入和撤回需要用户登录，提交时校验字段、图片尺寸与实际类型，并默认待审核。D1 保存投稿状态，R2 保存缩略图。
