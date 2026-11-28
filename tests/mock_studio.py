#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""镜流工作台 mock 服务器：仅用标准库模拟 studio/studio.py 的 API 契约，
供 jingliu CLI 的离线端到端测试使用。任务按 queued → running → done 推进。

用法（一般由测试代码启动）：
    python mock_studio.py --port 0
启动后向 stdout 打印一行 JSON：{"port": <port>}
"""

import argparse
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from urllib.parse import urlparse

VOICES = {
    'local-zh-female': '本地中文女声',
    'local-zh-male': '本地中文男声',
    'zh-CN-XiaoxiaoNeural': '晓晓（联网）',
}
IMAGE_EXT = {'.png', '.jpg', '.webp'}
VIDEO_EXT = {'.mp4', '.mov', '.webm', '.mkv'}
AUDIO_EXT = {'.mp3', '.wav', '.m4a'}
JOB_RUN_SECONDS = 0.8          # 单个任务运行时长（模拟）
FAIL_FIRST_MARK = 'FORCE_FAIL'  # 镜头标题含此标记时首次生成失败


class ApiFail(Exception):
    def __init__(self, status, text):
        self.status, self.text = status, text


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.projects = {}
        self.jobs = {}

    def new_project(self, name, aspect='9:16'):
        pid = uuid.uuid4().hex[:12]
        project = {'id': pid, 'name': name, 'aspect': aspect, 'updated': time.time(),
                   'brief': '', 'script': '', 'track': '', 'draft': None,
                   'assets': [], 'shots': [], 'exports': [], 'files': {}}
        self.projects[pid] = project
        return project

    def blank_shot(self, title='新镜头'):
        return {'id': uuid.uuid4().hex[:12], 'title': title, 'visual': '', 'prompt': '',
                'dialogue': '', 'first': '', 'last': '', 'clip': '', 'versions': [],
                'quality': 'normal', 'seconds': 4, 'seed': None}

    def enqueue(self, project, kind, **fields):
        job = {'id': uuid.uuid4().hex[:12], 'project_id': project['id'], 'kind': kind,
               'state': 'queued', 'progress': 0, 'message': '排队中', 'created': time.time()}
        job.update(fields)
        self.jobs[job['id']] = job
        return job

    @staticmethod
    def find_shot(project, shot_id):
        return next((s for s in project['shots'] if s['id'] == shot_id), None)

    @staticmethod
    def find_asset(project, asset_id):
        return next((a for a in project['assets'] if a['id'] == asset_id), None)


STORE = Store()


def parse_multipart(content_type, body):
    match = re.search(r'boundary=([^;]+)', content_type or '')
    if not match:
        raise ApiFail(400, '缺少 multipart boundary')
    boundary = match.group(1).encode()
    filename, payload = None, b''
    for part in body.split(b'--' + boundary):
        if b'filename="' in part:
            head, _, rest = part.partition(b'\r\n\r\n')
            name_match = re.search(rb'filename="([^"]+)"', head)
            filename = name_match.group(1).decode('utf-8') if name_match else None
            payload = rest.rsplit(b'\r\n', 1)[0]
    return filename, payload


def validate_upload(filename, payload):
    ext = PurePosixPath(filename or '').suffix.lower()
    if ext not in IMAGE_EXT | VIDEO_EXT | AUDIO_EXT:
        raise ApiFail(400, '支持 PNG、JPG、WebP、MP4、MOV、WebM、MKV 及常见音频。')
    looks_like_image = payload.startswith(b'\x89PNG') or payload[:3] == b'\xff\xd8\xff' \
        or payload[:4] == b'RIFF'
    if ext in IMAGE_EXT and not looks_like_image:
        raise ApiFail(400, '素材无法读取 · 不是有效图片。')
    return f'assets/{uuid.uuid4().hex[:12]}{ext}'


def finish_job(job, project):
    kind = job['kind']
    if project is None:
        job.update(state='done', progress=100, message='完成')
        return
    if kind == 'video':
        shot = STORE.find_shot(project, job.get('shot_id', ''))
        if shot is not None:
            relative = f'renders/{uuid.uuid4().hex[:10]}.mp4'
            project['files'][relative] = b'FAKE_MP4_' + shot['id'].encode()
            if shot['clip'] and shot['clip'] not in shot['versions']:
                shot['versions'].append(shot['clip'])
            shot['clip'] = relative
    elif kind == 'image':
        relative = f'assets/{uuid.uuid4().hex[:10]}.png'
        project['files'][relative] = b'FAKE_PNG'
        asset = STORE.find_asset(project, job.get('asset_id', ''))
        if asset is not None:
            asset['image'] = relative
        else:
            shot = STORE.find_shot(project, job.get('shot_id', ''))
            if shot is not None:
                shot['first'] = relative
    elif kind == 'draft':
        project['draft'] = {'shots': [{'title': f'草案镜头 {i + 1}', 'visual': '画面', 'prompt': '提示词',
                                       'dialogue': '', 'seconds': 4} for i in range(2)],
                            'assets': [{'name': '草案角色', 'kind': 'character', 'prompt': '外观'}],
                            'script': '草案剧本'}
    elif kind == 'export':
        name = uuid.uuid4().hex[:10]
        mp4, srt = f'renders/{name}.mp4', f'renders/{name}.srt'
        project['files'][mp4] = b'FAKE_EXPORT_MP4'
        project['files'][srt] = '1\n00:00:00,000 --> 00:00:04,000\n台词\n'.encode('utf-8')
        project['exports'].append({'id': name, 'name': 'mock export', 'file': mp4, 'subtitle': srt, 'created': time.time()})
    job.update(state='done', progress=100, message='完成')


def worker_loop():
    """串行任务线程：同真实工作台一样一次只跑一个任务。"""
    while True:
        job = None
        with STORE.lock:
            running = any(j['state'] == 'running' for j in STORE.jobs.values())
            # 带 HOLD 标记的任务永远保持排队，供取消逻辑做确定性测试
            queued = [j for j in STORE.jobs.values()
                      if j['state'] == 'queued' and 'HOLD' not in j.get('label', '')]
            if queued and not running:
                job = max(queued, key=lambda j: j['created'])
                job.update(state='running', progress=10, message='处理中')
        if job is None:
            time.sleep(0.05)
            continue
        time.sleep(JOB_RUN_SECONDS)
        with STORE.lock:
            project = STORE.projects.get(job['project_id'])
            fail_now = False
            if project is not None and job['kind'] == 'video' and not job.get('retried'):
                shot = STORE.find_shot(project, job.get('shot_id', ''))
                if shot is not None and FAIL_FIRST_MARK in shot.get('title', ''):
                    fail_now = True
            if fail_now:
                job.update(state='failed', progress=0, message='模拟生成失败（FORCE_FAIL）')
            else:
                finish_job(job, project)


def project_view(project):
    """对外返回的项目视图：不含原始文件字节（与真实工作台的 project.json 一致）。"""
    return {key: value for key, value in project.items() if key != 'files'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    # ---- 分发 ----

    def do_GET(self):
        self._dispatch(self.route_get)

    def do_POST(self):
        self._dispatch(self.route_post)

    def do_PATCH(self):
        self._dispatch(self.route_patch)

    def _dispatch(self, router):
        try:
            router(urlparse(self.path).path)
        except ApiFail as error:
            self._send(error.status, error.text.encode('utf-8'), 'text/plain; charset=utf-8')
        except Exception as error:  # noqa: BLE001
            self._send(500, f'mock 内部错误：{error!r}'.encode('utf-8'), 'text/plain; charset=utf-8')

    # ---- 基础工具 ----

    def _send(self, status, payload, content_type='application/json; charset=utf-8'):
        body = payload if isinstance(payload, bytes) else \
            json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b'{}'
        try:
            return json.loads(raw.decode('utf-8'))
        except ValueError:
            raise ApiFail(400, '请求体不是合法 JSON。')

    def _project(self, pid):
        project = STORE.projects.get(pid)
        if project is None:
            raise ApiFail(404, '项目不存在。')
        return project

    # ---- GET ----

    def route_get(self, path):
        if path == '/api/status':
            return self._send(200, {'comfy': True, 'workflow': True, 'models': ['qwen2.5:7b'],
                                    'ollama': True, 'voices': VOICES, 'community': '',
                                    'h3_confirmed': True})
        if path == '/api/identity':
            return self._send(200, {'app': 'jingliu', 'workspace': 'mock'})
        if path == '/api/projects':
            with STORE.lock:
                cards = [dict(id=p['id'], name=p['name'], aspect=p['aspect'], updated=p['updated'],
                              shots=len(p['shots']), cover='', exports=len(p['exports']))
                         for p in STORE.projects.values()]
            return self._send(200, sorted(cards, key=lambda c: c['updated'], reverse=True))
        if path == '/api/jobs':
            with STORE.lock:
                jobs = [dict(j) for j in STORE.jobs.values()]
            return self._send(200, sorted(jobs, key=lambda j: j['created'], reverse=True))
        match = re.fullmatch(r'/api/projects/([^/]+)', path)
        if match:
            return self._send(200, project_view(self._project(match.group(1))))
        match = re.fullmatch(r'/media/([^/]+)/([^/]+)/([^/]+)', path)
        if match:
            project = self._project(match.group(1))
            relative = f'{match.group(2)}/{match.group(3)}'
            data = project['files'].get(relative)
            if data is None:
                raise ApiFail(404, '媒体不存在。')
            return self._send(200, data, 'application/octet-stream')
        raise ApiFail(404, '未知的 GET 路径。')

    # ---- POST ----

    def route_post(self, path):
        if path == '/api/projects':
            body = self._json_body()
            name = str(body.get('name') or '').strip()
            if not name:
                raise ApiFail(400, '项目名不能为空。')
            if body.get('aspect') not in ('9:16', '16:9'):
                raise ApiFail(400, '画幅无效。')
            with STORE.lock:
                return self._send(200, project_view(STORE.new_project(name, body['aspect'])))
        if path == '/api/sample':
            with STORE.lock:
                project = STORE.new_project('月台机器人')
                shot = STORE.blank_shot('站台问候')
                shot.update(prompt='Fixed camera, a small robot blinks once.', seconds=2)
                project['shots'].append(shot)
            return self._send(200, project)
        match = re.fullmatch(r'/api/projects/([^/]+)/upload', path)
        if match:
            project = self._project(match.group(1))
            filename, payload = parse_multipart(self.headers.get('Content-Type'), self._read_body())
            with STORE.lock:
                relative = validate_upload(filename, payload)
                project['files'][relative] = payload
            return self._send(200, {'file': relative})
        match = re.fullmatch(r'/api/projects/([^/]+)/assets', path)
        if match:
            return self._send(200, project_view(self._assets(match.group(1), self._json_body())))
        match = re.fullmatch(r'/api/projects/([^/]+)/shots', path)
        if match:
            return self._send(200, project_view(self._shots(match.group(1), self._json_body())))
        match = re.fullmatch(r'/api/projects/([^/]+)/apply-draft', path)
        if match:
            return self._send(200, project_view(self._apply_draft(match.group(1))))
        match = re.fullmatch(r'/api/projects/([^/]+)/jobs', path)
        if match:
            return self._send(200, self._enqueue(match.group(1), self._json_body()))
        match = re.fullmatch(r'/api/jobs/([^/]+)/(retry|cancel)', path)
        if match:
            return self._send(200, self._manage_job(match.group(1), match.group(2)))
        raise ApiFail(404, '未知的 POST 路径。')

    def _read_body(self):
        length = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(length) if length else b''

    def _apply_draft(self, pid):
        project = self._project(pid)
        with STORE.lock:
            if not isinstance(project['draft'], dict):
                raise ApiFail(400, '暂无可导入的草案。')
            for item in project['draft']['shots']:
                shot = STORE.blank_shot(item['title'])
                shot.update(visual=item['visual'], prompt=item['prompt'], seconds=item['seconds'])
                project['shots'].append(shot)
            project['script'] = (project['script'] + '\n\n' + project['draft']['script']).strip()
            project['draft'] = None
        return project

    def _assets(self, pid, body):
        project = self._project(pid)
        with STORE.lock:
            item = STORE.find_asset(project, body.get('id')) if body.get('id') else None
            if body.get('remove'):
                if item is None:
                    raise ApiFail(404, '素材不存在。')
                project['assets'].remove(item)
                return project
            name, kind = str(body.get('name') or '').strip(), body.get('kind')
            if not name or kind not in ('character', 'scene', 'prop'):
                raise ApiFail(400, '请填写素材名称和类型。')
            voice = body.get('voice') or ''
            if voice and voice not in VOICES:
                raise ApiFail(400, '所选声线不受支持。')
            image = body.get('image') or ''
            if image and image not in project['files']:
                raise ApiFail(400, '参考图不存在。')
            if item is None:
                item = {'id': uuid.uuid4().hex[:12]}
                project['assets'].append(item)
            item.update(name=name, kind=kind, image=image,
                        prompt=body.get('prompt') or '', voice=voice)
            return project

    def _shots(self, pid, body):
        project = self._project(pid)
        action = body.get('action', 'save')
        with STORE.lock:
            if action == 'add':
                if len(project['shots']) >= 60:
                    raise ApiFail(400, '单个项目最多 60 镜。')
                project['shots'].append(STORE.blank_shot())
                return project
            shot = STORE.find_shot(project, body.get('id'))
            if shot is None:
                raise ApiFail(404, '镜头不存在。')
            if action == 'remove':
                project['shots'].remove(shot)
            elif action in ('up', 'down'):
                index = project['shots'].index(shot)
                other = index + (-1 if action == 'up' else 1)
                if 0 <= other < len(project['shots']):
                    project['shots'][index], project['shots'][other] = \
                        project['shots'][other], project['shots'][index]
            else:
                if 'quality' in body and body['quality'] not in ('quick', 'normal', 'detail'):
                    raise ApiFail(400, '请选择有效的生成规格。')
                if 'seconds' in body:
                    try:
                        seconds = float(body['seconds'])
                    except (TypeError, ValueError):
                        raise ApiFail(400, '镜头时长须在 0.5 至 12 秒之间。')
                    if not 0.5 <= seconds <= 12:
                        raise ApiFail(400, '镜头时长须在 0.5 至 12 秒之间。')
                    shot['seconds'] = seconds
                if 'seed' in body:
                    shot['seed'] = None if body['seed'] in (None, '') else int(body['seed'])
                for key, limit in (('title', 100), ('visual', 3000), ('prompt', 8000), ('dialogue', 2500)):
                    if key in body:
                        shot[key] = str(body[key])[:limit]
                for key in ('first', 'last', 'clip'):
                    if key in body:
                        value = body[key] or ''
                        if value and value not in project['files']:
                            raise ApiFail(400, f'{key} 文件不存在。')
                        if key == 'clip' and shot['clip'] and value != shot['clip'] \
                                and shot['clip'] not in shot['versions']:
                            shot['versions'].append(shot['clip'])
                        shot[key] = value
            return project

    def _enqueue(self, pid, body):
        project = self._project(pid)
        kind = body.get('kind')
        with STORE.lock:
            if kind == 'video':
                steps = body.get('steps', 20)
                if not (isinstance(steps, int) and 4 <= steps <= 40):
                    raise ApiFail(400, '采样步数请使用 4–40 的整数。')
                shots = [STORE.find_shot(project, body['shot_id'])] if body.get('shot_id') \
                    else [s for s in project['shots'] if s['first'] and not s['clip']]
                shots = [s for s in shots if s is not None]
                if not shots:
                    raise ApiFail(400, '没有待生成的镜头。请先选择首帧。')
                for shot in shots:
                    if not shot['first']:
                        raise ApiFail(400, f'请为「{shot["title"]}」设置首帧。')
                    if not (shot['prompt'] or shot['visual']):
                        raise ApiFail(400, f'请为「{shot["title"]}」填写动作提示词。')
                return [STORE.enqueue(project, 'video', shot_id=s['id'], label=s['title'], steps=steps)
                        for s in shots]
            if kind == 'image':
                if body.get('asset_id'):
                    asset = STORE.find_asset(project, body['asset_id'])
                    if asset is None:
                        raise ApiFail(404, '素材不存在。')
                    if not asset['prompt'] or asset['image']:
                        raise ApiFail(400, '请为没有图片的素材填写参考图提示词。')
                    return [STORE.enqueue(project, 'image', asset_id=asset['id'], label='参考草图')]
                shot = STORE.find_shot(project, body.get('shot_id'))
                if shot is None:
                    raise ApiFail(404, '镜头不存在。')
                if shot['first'] or not (shot['visual'] or shot['prompt']):
                    raise ApiFail(400, '请为没有首帧的镜头填写画面描述。')
                return [STORE.enqueue(project, 'image', shot_id=shot['id'], label='首帧草图')]
            if kind == 'draft':
                if not str(body.get('brief') or '').strip():
                    raise ApiFail(400, '请先输入创意或已有剧本。')
                count, target = int(body.get('count', 5)), int(body.get('seconds', 30))
                if not 1 <= count <= 12 or not 5 <= target <= 120:
                    raise ApiFail(400, '请使用 1–12 镜、5–120 秒。')
                return [STORE.enqueue(project, 'draft', label='剧本与分镜草案')]
            if kind == 'export':
                if not project['shots']:
                    raise ApiFail(400, '请先创建分镜。')
                options = {'size': body.get('size', '720'), 'subtitles': body.get('subtitles', True) is True,
                           'audio': body.get('audio', 'source'), 'voice': body.get('voice', 'local-zh-female')}
                if options['size'] not in ('720', '1080') \
                        or options['audio'] not in ('source', 'tts', 'track', 'silent') \
                        or options['voice'] not in VOICES:
                    raise ApiFail(400, '导出选项无效。')
                for shot in project['shots']:
                    if not (shot['clip'] or shot['first']):
                        raise ApiFail(400, f'请先为「{shot["title"]}」设置首帧。')
                return [STORE.enqueue(project, 'export', label='短剧成片', options=options)]
            raise ApiFail(400, '任务类型无效。')

    def _manage_job(self, job_id, action):
        job = STORE.jobs.get(job_id)
        if job is None:
            raise ApiFail(404, '任务不存在。')
        with STORE.lock:
            if action == 'cancel':
                if job['state'] != 'queued':
                    raise ApiFail(409, '只能取消尚未执行的任务。')
                job.update(state='cancelled', message='已取消')
                return job
            if job['state'] != 'failed':
                raise ApiFail(409, '只有失败的任务可以重试。')
            project = STORE.projects.get(job['project_id'])
            return STORE.enqueue(project, job['kind'], shot_id=job.get('shot_id'),
                                 asset_id=job.get('asset_id'), label=job.get('label', ''),
                                 steps=job.get('steps', 20), retried=True)

    # ---- PATCH ----

    def route_patch(self, path):
        match = re.fullmatch(r'/api/projects/([^/]+)', path)
        if not match:
            raise ApiFail(404, '未知的 PATCH 路径。')
        project = self._project(match.group(1))
        body = self._json_body()
        with STORE.lock:
            for field, limit in (('name', 100), ('brief', 6000), ('script', 20000)):
                if field in body:
                    value = str(body[field])[:limit]
                    if field == 'name' and not value.strip():
                        raise ApiFail(400, '项目名不能为空。')
                    project[field] = value
            if 'track' in body:
                track = body['track'] or ''
                if track and track not in project['files']:
                    raise ApiFail(400, '音轨文件不存在。')
                project['track'] = track
        return self._send(200, project_view(project))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    threading.Thread(target=worker_loop, daemon=True).start()
    print(json.dumps({'port': server.server_address[1]}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
