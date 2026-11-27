#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""镜流（Jingliu）工作台 CLI 包装器。

纯 Python 标准库实现，供各类本地 Agent harness（WorkBuddy / Codex / zcode 等）
通过 shell 调用，驱动镜流工作台完成 AI 短剧全流程：
状态检查 → 项目 → 素材 → 分镜 → 生成任务（草图/视频/剧本草案）→ 导出 → 下载。

工作台默认地址 http://127.0.0.1:7861，仅监听本机。
可用环境变量 JINGLIU_BASE 覆盖，或对每个命令传 --base。

所有命令成功时输出 JSON（UTF-8）；失败时向 stderr 输出错误并返回非零退出码。
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_BASE = os.environ.get("JINGLIU_BASE", "http://127.0.0.1:7861")
TERMINAL_STATES = {"done", "failed", "cancelled"}


class ApiError(Exception):
    pass


def request(method, path, body=None, raw=None, headers=None, timeout=30, base=DEFAULT_BASE):
    url = base.rstrip("/") + path
    data = None
    hdrs = dict(headers or {})
    if raw is not None:
        data = raw
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    if method not in ("GET", "HEAD"):
        # 工作台的 local_only 中间件要求写操作携带此头（防跨站）
        hdrs["X-Studio-Request"] = "1"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace").strip()
        try:
            parsed = json.loads(detail)
            detail = parsed.get("message") or parsed.get("error") or parsed.get("reason") or detail
        except (ValueError, AttributeError):
            pass
        raise ApiError(f"HTTP {error.code} · {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise ApiError(
            f"无法连接工作台 {url}（{error.reason}）。"
            "请确认镜流已启动：运行 python -B deploy/installer.py start，或双击「打开镜流」。"
        ) from error
    if not text:
        return None
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        return json.loads(text)
    return text


def upload_file(project_id, filepath, base=DEFAULT_BASE):
    path = Path(filepath)
    if not path.is_file():
        raise ApiError(f"文件不存在：{path}")
    boundary = uuid.uuid4().hex
    body = bytearray()
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    body += path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")
    return request(
        "POST",
        f"/api/projects/{project_id}/upload",
        raw=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=600,
        base=base,
    )


def download_media(project_id, relative, out, base=DEFAULT_BASE):
    parts = relative.strip("/").split("/", 1)
    if len(parts) != 2:
        raise ApiError(f"媒体路径须形如 category/name，例如 exports/xxx.mp4，收到：{relative}")
    url = f"{base.rstrip('/')}/media/{project_id}/{parts[0]}/{parts[1]}?download=1"
    try:
        with urllib.request.urlopen(url, timeout=600) as resp, open(out, "wb") as fh:
            fh.write(resp.read())
    except urllib.error.HTTPError as error:
        raise ApiError(f"HTTP {error.code} · 媒体不存在或路径无效：{relative}") from error
    return {"out": str(Path(out).resolve()), "size": Path(out).stat().st_size, "path": relative}


def wait_job(job_id, timeout_s=7200, interval=5, base=DEFAULT_BASE):
    deadline = time.time() + timeout_s
    job = None
    while True:
        jobs = request("GET", "/api/jobs", base=base)
        job = next((item for item in jobs if item.get("id") == job_id), None)
        if job is None:
            raise ApiError(f"任务不存在：{job_id}")
        if job.get("state") in TERMINAL_STATES:
            return job
        if time.time() > deadline:
            return {"state": job.get("state"), "timeout": True,
                    "message": f"等待超时（{timeout_s}s），任务仍在 {job.get('state')}", "job": job}
        progress = job.get("progress")
        message = job.get("message", "")
        print(f"[等待] {job.get('state')} {('%d%%' % progress) if isinstance(progress, (int, float)) else ''} {message}".rstrip(), file=sys.stderr)
        time.sleep(interval)


# ---------------------------------------------------------------- argparse

def add_base(parser):
    parser.add_argument("--base", default=DEFAULT_BASE, help="工作台地址（默认 %(default)s）")


def main():
    parser = argparse.ArgumentParser(prog="jingliu", description="镜流工作台 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="工作台与服务状态（ComfyUI/Ollama/声线）")
    add_base(p)

    p = sub.add_parser("projects", help="列出项目")
    add_base(p)

    p = sub.add_parser("project", help="查看项目完整数据")
    p.add_argument("--id", required=True)
    add_base(p)

    p = sub.add_parser("create", help="新建项目")
    p.add_argument("--name", required=True)
    p.add_argument("--aspect", default="9:16", choices=["9:16", "16:9"])
    add_base(p)

    p = sub.add_parser("sample", help="导入内置「月台机器人」示例项目")
    add_base(p)

    p = sub.add_parser("edit-project", help="修改项目简介/剧本/音轨")
    p.add_argument("--id", required=True)
    p.add_argument("--name")
    p.add_argument("--brief")
    p.add_argument("--script")
    p.add_argument("--track", help="项目音轨相对路径（assets/...，留空字符串清除）")
    add_base(p)

    p = sub.add_parser("upload", help="上传素材文件（图/视频/音频）")
    p.add_argument("--id", required=True, help="项目 ID")
    p.add_argument("--file", required=True)
    add_base(p)

    p = sub.add_parser("asset", help="新增/修改/删除素材（角色/场景/道具）")
    p.add_argument("--id", required=True, help="项目 ID")
    p.add_argument("--asset-id", help="已有素材 ID（修改时必填）")
    p.add_argument("--name", help="素材名称（与台词角色名一致）")
    p.add_argument("--kind", choices=["character", "scene", "prop"])
    p.add_argument("--image", help="参考图相对路径（assets/...）")
    p.add_argument("--prompt", help="参考图提示词（无图时可用于生成草图）")
    p.add_argument("--voice", help="配音声线键名，如 local-zh-female")
    p.add_argument("--remove", action="store_true", help="删除该素材（需 --asset-id）")
    add_base(p)

    p = sub.add_parser("shot", help="分镜操作：add/save/remove/up/down")
    p.add_argument("--id", required=True, help="项目 ID")
    p.add_argument("--action", default="save", choices=["add", "save", "remove", "up", "down"])
    p.add_argument("--shot-id", help="镜头 ID（save/remove/up/down 必填）")
    p.add_argument("--title")
    p.add_argument("--visual", help="画面描述")
    p.add_argument("--prompt", help="动作提示词（主体/动作/环境/镜头运动）")
    p.add_argument("--dialogue", help="台词，每行「角色名：台词」")
    p.add_argument("--first", help="首帧图相对路径")
    p.add_argument("--last", help="尾帧图相对路径")
    p.add_argument("--clip", help="已生成镜头视频相对路径（versions/...）")
    p.add_argument("--quality", choices=["quick", "normal", "detail"])
    p.add_argument("--seconds", type=float, help="时长 0.5–12 秒")
    p.add_argument("--seed", type=int, help="随机种子 0–4294967295")
    add_base(p)

    p = sub.add_parser("draft", help="用本地编剧模型（Ollama）生成剧本分镜草案")
    p.add_argument("--id", required=True)
    p.add_argument("--brief", required=True, help="创意或已有剧本")
    p.add_argument("--count", type=int, default=5, help="镜头数 1–12")
    p.add_argument("--seconds", type=int, default=30, help="目标总时长 5–120 秒")
    p.add_argument("--model", help="Ollama 模型名（默认自动选择）")
    add_base(p)

    p = sub.add_parser("apply-draft", help="把已生成的草案导入为正式分镜")
    p.add_argument("--id", required=True)
    add_base(p)

    p = sub.add_parser("video", help="排队生成镜头视频（未传 --shot-id 时生成所有待生成镜头）")
    p.add_argument("--id", required=True)
    p.add_argument("--shot-id", help="只生成这一个镜头")
    p.add_argument("--steps", type=int, default=20, help="采样步数 4–40（验收短镜头可用 4）")
    add_base(p)

    p = sub.add_parser("sketch", help="生成首帧草图或素材参考图（H3 抽帧）")
    p.add_argument("--id", required=True)
    p.add_argument("--shot-id", help="为无首帧的镜头生成草图")
    p.add_argument("--asset-id", help="为无参考图的素材生成草图")
    add_base(p)

    p = sub.add_parser("export", help="拼接导出成片 MP4（含可选配音/字幕）")
    p.add_argument("--id", required=True)
    p.add_argument("--size", default="720", choices=["720", "1080"])
    p.add_argument("--audio", default="source", choices=["source", "tts", "track", "silent"],
                   help="source=镜头原声 tts=按台词合成 track=项目音轨 silent=静音")
    p.add_argument("--voice", default="local-zh-female", help="默认声线（角色自带声线优先）")
    p.add_argument("--subtitles", dest="subtitles", action="store_true", default=True)
    p.add_argument("--no-subtitles", dest="subtitles", action="store_false")
    p.add_argument("--name", default="短剧成片")
    add_base(p)

    p = sub.add_parser("jobs", help="列出任务（可按项目过滤）")
    p.add_argument("--project", help="按项目 ID 过滤")
    add_base(p)

    p = sub.add_parser("wait", help="轮询等待任务结束")
    p.add_argument("--job-id", required=True)
    p.add_argument("--timeout", type=int, default=7200, help="超时秒数（默认 7200）")
    p.add_argument("--interval", type=int, default=5, help="轮询间隔秒数")
    add_base(p)

    for name, action in (("retry", "重试失败任务"), ("cancel", "取消排队中任务")):
        p = sub.add_parser(name, help=action)
        p.add_argument("--job-id", required=True)
        add_base(p)

    p = sub.add_parser("download", help="下载项目媒体（成片/字幕/素材）")
    p.add_argument("--id", required=True, help="项目 ID")
    p.add_argument("--path", required=True, help="相对路径，如 exports/xxx.mp4 或 exports/xxx.srt")
    p.add_argument("--out", required=True, help="保存到的本地文件路径")
    add_base(p)

    args = parser.parse_args()
    base = getattr(args, "base", DEFAULT_BASE)
    try:
        result = dispatch(args, base)
    except ApiError as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def dispatch(args, base):
    cmd = args.command
    if cmd == "status":
        return request("GET", "/api/status", base=base)
    if cmd == "projects":
        return request("GET", "/api/projects", base=base)
    if cmd == "project":
        return request("GET", f"/api/projects/{args.id}", base=base)
    if cmd == "create":
        return request("POST", "/api/projects", {"name": args.name, "aspect": args.aspect}, base=base)
    if cmd == "sample":
        return request("POST", "/api/sample", {}, base=base)
    if cmd == "edit-project":
        body = {}
        for field in ("name", "brief", "script", "track"):
            value = getattr(args, field)
            if value is not None:
                body[field] = value
        return request("PATCH", f"/api/projects/{args.id}", body, base=base)
    if cmd == "upload":
        return upload_file(args.id, args.file, base=base)
    if cmd == "asset":
        body = {}
        if args.asset_id:
            body["id"] = args.asset_id
        if args.remove:
            body["remove"] = True
        for field in ("name", "kind", "image", "prompt", "voice"):
            value = getattr(args, field)
            if value is not None:
                body[field] = value
        return request("POST", f"/api/projects/{args.id}/assets", body, base=base)
    if cmd == "shot":
        body = {"action": args.action}
        if args.shot_id:
            body["id"] = args.shot_id
        for field in ("title", "visual", "prompt", "dialogue", "first", "last", "clip", "quality"):
            value = getattr(args, field)
            if value is not None:
                body[field] = value
        if args.seconds is not None:
            body["seconds"] = args.seconds
        if args.seed is not None:
            body["seed"] = args.seed
        return request("POST", f"/api/projects/{args.id}/shots", body, base=base)
    if cmd == "draft":
        body = {"brief": args.brief, "count": args.count, "seconds": args.seconds}
        if args.model:
            body["model"] = args.model
        return request("POST", f"/api/projects/{args.id}/jobs", {"kind": "draft", **body}, base=base)
    if cmd == "apply-draft":
        return request("POST", f"/api/projects/{args.id}/apply-draft", {}, base=base)
    if cmd == "video":
        body = {"kind": "video", "steps": args.steps}
        if args.shot_id:
            body["shot_id"] = args.shot_id
        return request("POST", f"/api/projects/{args.id}/jobs", body, base=base)
    if cmd == "sketch":
        body = {"kind": "image"}
        if args.asset_id:
            body["asset_id"] = args.asset_id
        elif args.shot_id:
            body["shot_id"] = args.shot_id
        else:
            raise ApiError("sketch 需要 --shot-id 或 --asset-id")
        return request("POST", f"/api/projects/{args.id}/jobs", body, base=base)
    if cmd == "export":
        body = {"kind": "export", "size": args.size, "audio": args.audio,
                "voice": args.voice, "subtitles": args.subtitles, "name": args.name}
        return request("POST", f"/api/projects/{args.id}/jobs", body, base=base)
    if cmd == "jobs":
        jobs = request("GET", "/api/jobs", base=base)
        if args.project:
            jobs = [job for job in jobs if job.get("project_id") == args.project]
        return jobs
    if cmd == "wait":
        return wait_job(args.job_id, args.timeout, args.interval, base=base)
    if cmd in ("retry", "cancel"):
        return request("POST", f"/api/jobs/{args.job_id}/{cmd}", {}, base=base)
    if cmd == "download":
        return download_media(args.id, args.path, args.out, base=base)
    raise ApiError(f"未知命令：{cmd}")


if __name__ == "__main__":
    main()
