"""Short drama workbench. Run with the existing ComfyUI Python environment."""

import argparse
import asyncio
import copy
import hashlib
import json
import mimetypes
import os
import re
import shutil
import time
import uuid
import webbrowser
from pathlib import Path

from aiohttp import ClientSession, web
from PIL import Image

import engine

HERE = Path(__file__).resolve().parent
STATIC = HERE / 'web'
ACTIVE = {'queued', 'running'}
ID = r'[a-f0-9]{32}'
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp'}
VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.webm'}
AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}


def uid():
    return uuid.uuid4().hex


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def require(condition, message, status=400):
    if not condition:
        raise {400: web.HTTPBadRequest, 404: web.HTTPNotFound, 409: web.HTTPConflict}[status](text=message)


def string(value, limit=10000):
    return str(value or '').strip()[:limit]


def seconds(value, default=4):
    try:
        value = float(value)
        if 0.5 <= value <= 12:
            return round(value * engine.FPS) / engine.FPS
    except (TypeError, ValueError):
        pass
    return default


def blank_shot(title='新镜头'):
    return {'id': uid(), 'title': title, 'seconds': 4, 'visual': '', 'prompt': '', 'dialogue': '',
            'first': '', 'last': '', 'clip': '', 'quality': 'normal', 'seed': None, 'versions': []}


class Studio:
    def __init__(self, data):
        self.data = data
        self.projects = data / 'projects'
        self.jobs_dir = data / 'jobs'
        self.projects.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(exist_ok=True)
        self.jobs = {job['id']: job for file in self.jobs_dir.glob('*.json') if (job := read_json(file))}
        for job in self.jobs.values():
            if job['state'] == 'running':
                job.update(state='failed', message='工作台重启时任务尚未完成，可以重试。')
                self.save_job(job)
        self.wake = asyncio.Event()

    def folder(self, project_id):
        require(re.fullmatch(ID, project_id), '项目不存在。', 404)
        return self.projects / project_id

    def project(self, project_id):
        file = self.folder(project_id) / 'project.json'
        require(file.is_file(), '项目不存在。', 404)
        return read_json(file)

    def save(self, project):
        project['updated'] = time.time()
        write_json(self.folder(project['id']) / 'project.json', project)

    def save_job(self, job):
        job['updated'] = time.time()
        write_json(self.jobs_dir / (job['id'] + '.json'), job)

    def busy(self, project_id):
        return any(job['project_id'] == project_id and job['state'] in ACTIVE for job in self.jobs.values())

    def editable(self, project_id):
        require(not self.busy(project_id), '本项目有排队或运行中的任务。完成后即可继续编辑。', 409)

    def new(self, name, aspect):
        require(name, '请输入项目名称。')
        require(aspect in ('9:16', '16:9'), '请选择有效画幅。')
        project = {'id': uid(), 'name': name, 'aspect': aspect, 'brief': '', 'script': '', 'assets': [],
                   'shots': [], 'exports': [], 'track': '', 'draft': None}
        folder = self.folder(project['id'])
        (folder / 'assets').mkdir(parents=True)
        (folder / 'renders').mkdir()
        self.save(project)
        return project

    def sample(self):
        source = HERE / 'demo' / 'robot.png'
        require(source.is_file(), '找不到随工作台分发的示例首帧。', 404)
        project = self.new('示例 · 月台机器人', '9:16')
        folder = self.folder(project['id'])
        asset_id = uid()
        image = f'assets/{asset_id}.png'
        shutil.copyfile(source, folder / image)
        description = '夜色里的月台上，一只青绿色机器人轻轻眨眼。固定镜头，背景灯光微微闪动。'
        prompt = ('Static locked camera. A small mint green robot on a deep blue space station platform blinks once. '
                  'Preserve its exact geometric design, silhouette and color. Soft ambient light, subtle background motion, no lettering.')
        project['brief'] = description
        project['script'] = '月台上的机器人收到信号。它轻轻眨眼，静静等候下一班车。'
        project['assets'].append({'id': asset_id, 'kind': 'character', 'name': '月台机器人',
                                  'prompt': description, 'voice': '', 'image': image})
        shot = blank_shot('信号抵达')
        shot.update(seconds=2, first=image, quality='quick', seed=63, visual=description,
                    prompt=prompt, dialogue='旁白：信号抵达。')
        project['shots'].append(shot)
        self.save(project)
        return project

    def enqueue(self, project, kind, **fields):
        job = {'id': uid(), 'project_id': project['id'], 'project_name': project['name'], 'kind': kind,
               'state': 'queued', 'progress': 0, 'message': '等待执行', 'created': time.time(), **fields}
        self.jobs[job['id']] = job
        self.save_job(job)
        self.wake.set()
        return job

    async def worker(self):
        while True:
            job = next((item for item in self.jobs.values() if item['state'] == 'queued'), None)
            if job is None:
                await self.comfy.release()
                self.wake.clear()
                if not any(item['state'] == 'queued' for item in self.jobs.values()):
                    await self.wake.wait()
                continue

            def update(progress, message):
                job.update(progress=max(job['progress'], round(progress)), message=message)
                self.save_job(job)

            job.update(state='running', started=time.time())
            update(1, '正在准备')
            try:
                project = self.project(job['project_id'])
                folder = self.folder(project['id'])
                if job['kind'] not in ('video', 'image'):
                    await self.comfy.release()
                if job['kind'] in ('video', 'image'):
                    if job.get('prompt_id'):
                        prompt_id = job['prompt_id']
                        queue = await engine.service_info(self.session, engine.COMFY_URL + '/queue')
                        history = await engine.service_info(self.session, engine.COMFY_URL + '/history/' + prompt_id)
                        ids = {item[1] for items in (queue or {}).values() if isinstance(items, list) for item in items if len(item) > 1}
                        if prompt_id not in ids and prompt_id not in (history or {}):
                            job.pop('prompt_id', None)
                    if job['kind'] == 'video':
                        shot = self.find_shot(project, job['shot_id'])
                        path = await self.comfy.video(folder, project, shot, job, update)
                        if shot['clip'] and shot['clip'] not in shot['versions']:
                            shot['versions'].append(shot['clip'])
                        shot['clip'] = path
                    else:
                        if job.get('asset_id'):
                            target = next((a for a in project['assets'] if a['id'] == job['asset_id']), None)
                            require(target is not None, '参考素材已移除。', 404)
                            field = 'image'
                            description = target['prompt']
                            framing = {'character': 'Full-body character concept reference, one character, simple backdrop.',
                                       'scene': 'Establishing shot of the location, no characters.',
                                       'prop': 'Product-style reference of a single object, uncluttered backdrop.'}[target['kind']]
                        else:
                            target = self.find_shot(project, job['shot_id'])
                            field = 'first'
                            description = target['visual'] or target['prompt']
                            framing = 'A short drama storyboard frame, coherent staging and cinematic light.'
                        require(not target[field], '已有参考图，生成草图前请先清除该参考图。', 409)
                        sketch = blank_shot(target.get('title') or target.get('name'))
                        sketch.update(seconds=0.75, quality='quick', prompt=f'Static locked shot. {framing} {description}')
                        path = await self.comfy.video(folder, project, sketch, job, update)
                        target[field] = path
                    job['file'] = path
                elif job['kind'] == 'draft':
                    update(20, 'Ollama 正在编写剧本与分镜')
                    project['draft'] = await engine.draft(self.session, project, **job['options'])
                else:
                    path = await engine.encode(folder, project, job, update)
                    item = {'id': job['id'], 'name': job['label'], 'file': path, 'created': time.time()}
                    if (folder / f"renders/{job['id']}.srt").exists():
                        item['subtitle'] = f"renders/{job['id']}.srt"
                    project['exports'].append(item)
                    job['file'] = path
                self.save(project)
                job['state'] = 'done'
                update(100, '已完成')
            except asyncio.CancelledError:
                job['state'] = 'failed'
                update(job['progress'], '工作台已关闭，可以重新启动后重试。')
                raise
            except Exception as error:
                job['state'] = 'failed'
                update(job['progress'], getattr(error, 'text', str(error))[:2500] or type(error).__name__)

    @staticmethod
    def find_shot(project, shot_id):
        shot = next((item for item in project['shots'] if item['id'] == shot_id), None)
        require(shot is not None, '镜头不存在。', 404)
        return shot

    def media_file(self, project, relative, extensions):
        require(isinstance(relative, str) and re.fullmatch(r'(assets|renders)/[a-f0-9]{32}\.[a-z0-9]+', relative), '素材路径无效。')
        folder = self.folder(project['id']).resolve()
        path = (folder / relative).resolve()
        require(path.is_relative_to(folder) and path.is_file() and path.suffix in extensions, '素材文件不存在或格式不支持。', 404)
        return path


@web.middleware
async def local_only(request, handler):
    host = request.host.split(':', 1)[0]
    if host not in {'127.0.0.1', 'localhost'}:
        raise web.HTTPForbidden(text='工作台仅支持本机访问。')
    if request.method not in {'GET', 'HEAD'}:
        if request.headers.get('X-Studio-Request') != '1' or request.headers.get('Origin') not in (
            None, f'http://{request.host}',
        ):
            raise web.HTTPForbidden(text='请从本机工作台页面发起操作。')
    try:
        return await handler(request)
    except web.HTTPException as error:
        if request.path.startswith('/api/'):
            return web.json_response({'error': error.text}, status=error.status)
        raise
    except (ValueError, TypeError, KeyError) as error:
        return web.json_response({'error': f'请求数据无效 · {error}'}, status=400)


def api(studio):
    routes = web.RouteTableDef()

    @routes.get('/')
    async def index(request):
        return web.FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-cache'})

    @routes.get('/static/{name:app\\.js|onboarding\\.js|waiting\\.js|waiting\\.css|style\\.css}')
    async def static(request):
        return web.FileResponse(STATIC / request.match_info['name'], headers={'Cache-Control': 'no-cache'})

    @routes.get('/api/status')
    async def status(request):
        comfy, ollama = await asyncio.gather(
            engine.service_info(studio.session, engine.COMFY_URL + '/system_stats'),
            engine.service_info(studio.session, engine.OLLAMA + '/api/tags'),
        )
        return web.json_response({'comfy': comfy is not None, 'workflow': engine.WORKFLOW.is_file(),
                                  'models': [item['name'] for item in (ollama or {}).get('models', [])],
                                  'ollama': ollama is not None, 'voices': engine.VOICES,
                                  'community': os.environ.get('JINGLIU_COMMUNITY', ''),
                                  'h3_confirmed': bool(os.environ.get('JINGLIU_REGION'))})

    @routes.get('/api/identity')
    async def identity(request):
        workspace = hashlib.sha256(os.path.normcase(str(studio.data.resolve())).encode('utf-8')).hexdigest()
        return web.json_response({'app': 'jingliu', 'workspace': workspace})

    @routes.get('/api/projects')
    async def list_projects(request):
        projects = [read_json(path) for path in studio.projects.glob('*/project.json')]
        cards = [dict(id=p['id'], name=p['name'], aspect=p['aspect'], updated=p['updated'], shots=len(p['shots']),
                      cover=next((s['first'] for s in reversed(p['shots']) if s['first']), ''), exports=len(p['exports'])) for p in projects]
        return web.json_response(sorted(cards, key=lambda p: p['updated'], reverse=True))

    @routes.post('/api/projects')
    async def create_project(request):
        body = await request.json()
        return web.json_response(studio.new(string(body.get('name'), 100), body.get('aspect', '9:16')))

    @routes.post('/api/sample')
    async def sample(request):
        return web.json_response(studio.sample())

    @routes.get('/api/projects/{project}')
    async def get_project(request):
        return web.json_response(studio.project(request.match_info['project']))

    @routes.patch('/api/projects/{project}')
    async def edit_project(request):
        project = studio.project(request.match_info['project'])
        studio.editable(project['id'])
        body = await request.json()
        studio.editable(project['id'])
        project = studio.project(project['id'])
        for field, limit in [('name', 100), ('brief', 6000), ('script', 20000)]:
            if field in body:
                value = string(body[field], limit)
                require(field != 'name' or value, '项目名不能为空。')
                project[field] = value
        if 'track' in body:
            value = body['track']
            if value:
                studio.media_file(project, value, AUDIO_EXT)
            project['track'] = value or ''
        studio.save(project)
        return web.json_response(project)

    @routes.post('/api/projects/{project}/upload')
    async def upload(request):
        project = studio.project(request.match_info['project'])
        studio.editable(project['id'])
        reader = await request.multipart()
        field = await reader.next()
        require(field is not None and field.name == 'file' and field.filename, '请选择文件。')
        ext = Path(field.filename).suffix.lower()
        require(ext in IMAGE_EXT | VIDEO_EXT | AUDIO_EXT, '支持 PNG、JPG、WebP、MP4、MOV、WebM、MKV 及常见音频。')
        relative = f'assets/{uid()}{ext}'
        path = studio.folder(project['id']) / relative
        try:
            size = 0
            with path.open('wb') as out:
                while chunk := await field.read_chunk(256 * 1024):
                    size += len(chunk)
                    require(size <= 300 * 1024 * 1024, '单个文件最多 300 MB。')
                    out.write(chunk)
            if ext in IMAGE_EXT:
                def verify_image():
                    with Image.open(path) as picture:
                        picture.verify()
                await asyncio.to_thread(verify_image)
            else:
                info = await engine.probe(path)
                require(any(s['codec_type'] == ('video' if ext in VIDEO_EXT else 'audio') for s in info['streams']), '文件缺少所需媒体流。')
        except Exception as error:
            path.unlink(missing_ok=True)
            raise web.HTTPBadRequest(text=f'素材无法读取 · {getattr(error, "text", str(error))[:400]}') from error
        return web.json_response({'file': relative})

    @routes.get('/media/{project}/{category}/{name}')
    async def media(request):
        project = studio.project(request.match_info['project'])
        relative = f"{request.match_info['category']}/{request.match_info['name']}"
        path = studio.media_file(project, relative, IMAGE_EXT | VIDEO_EXT | AUDIO_EXT | {'.srt'})
        headers = {'Content-Type': mimetypes.guess_type(path.name)[0] or 'application/octet-stream', 'X-Content-Type-Options': 'nosniff'}
        if request.query.get('download') == '1':
            headers['Content-Disposition'] = f'attachment; filename="{path.name}"'
        return web.FileResponse(path, headers=headers)

    @routes.post('/api/projects/{project}/assets')
    async def edit_asset(request):
        body = await request.json()
        project = studio.project(request.match_info['project'])
        studio.editable(project['id'])
        item = next((a for a in project['assets'] if a['id'] == body.get('id')), None)
        require(not body.get('id') or item is not None, '素材不存在。', 404)
        if body.get('remove'):
            require(item is not None, '素材不存在。', 404)
            project['assets'].remove(item)
        else:
            name, kind, image = string(body.get('name'), 100), body.get('kind'), body.get('image') or ''
            voice = body.get('voice') or ''
            require(name and kind in ('character', 'scene', 'prop'), '请填写素材名称和类型。')
            require(not voice or voice in engine.VOICES, '所选声线不受支持。')
            if image:
                studio.media_file(project, image, IMAGE_EXT)
            if item is None:
                item = {'id': uid()}
                project['assets'].append(item)
            item.update(name=name, kind=kind, image=image, prompt=string(body.get('prompt')), voice=voice)
        studio.save(project)
        return web.json_response(project)

    @routes.post('/api/projects/{project}/shots')
    async def edit_shot(request):
        body = await request.json()
        project = studio.project(request.match_info['project'])
        studio.editable(project['id'])
        action = body.get('action', 'save')
        if action == 'add':
            require(len(project['shots']) < 60, '单个项目最多 60 镜。')
            project['shots'].append(blank_shot())
        else:
            shot = studio.find_shot(project, body.get('id'))
            if action == 'remove':
                project['shots'].remove(shot)
            elif action in ('up', 'down'):
                i = project['shots'].index(shot)
                j = i + (-1 if action == 'up' else 1)
                if 0 <= j < len(project['shots']):
                    project['shots'][i], project['shots'][j] = project['shots'][j], shot
            else:
                values = {}
                for key, limit in [('title', 100), ('visual', 3000), ('prompt', 8000), ('dialogue', 2500)]:
                    if key in body:
                        values[key] = string(body[key], limit)
                for key in ('first', 'last', 'clip'):
                    if key in body:
                        value = body[key] or ''
                        if value:
                            studio.media_file(project, value, VIDEO_EXT if key == 'clip' else IMAGE_EXT)
                        values[key] = value
                if 'quality' in body:
                    require(body['quality'] in ('quick', 'normal', 'detail'), '请选择有效的生成规格。')
                    values['quality'] = body['quality']
                if 'seconds' in body:
                    value = seconds(body['seconds'], None)
                    require(value is not None, '镜头时长须在 0.5 至 12 秒之间。')
                    values['seconds'] = value
                if 'seed' in body:
                    value = None if body['seed'] in (None, '') else int(body['seed'])
                    require(value is None or 0 <= value <= 2**32 - 1, '种子须为 0 到 4294967295 的整数。')
                    values['seed'] = value
                if 'clip' in values and shot['clip'] and values['clip'] != shot['clip'] and shot['clip'] not in shot['versions']:
                    shot['versions'].append(shot['clip'])
                shot.update(values)
        studio.save(project)
        return web.json_response(project)

    @routes.post('/api/projects/{project}/apply-draft')
    async def apply_draft(request):
        project = studio.project(request.match_info['project'])
        studio.editable(project['id'])
        draft = project['draft']
        require(isinstance(draft, dict), '暂无可导入的草案。')
        drafted_shots = [item for item in draft['shots'] if isinstance(item, dict)][:20]
        require(drafted_shots and len(project['shots']) + len(drafted_shots) <= 60, '草案无有效分镜，或已超过 60 镜上限。')
        for item in drafted_shots:
            shot = blank_shot(string(item.get('title'), 100) or '新镜头')
            shot.update(seconds=seconds(item.get('seconds')), visual=string(item.get('visual'), 3000),
                        prompt=string(item.get('prompt'), 8000), dialogue=string(item.get('dialogue'), 2500))
            project['shots'].append(shot)
        candidates = draft.get('assets')
        for asset in candidates[:24] if isinstance(candidates, list) else []:
            if not isinstance(asset, dict):
                continue
            name = string(asset.get('name'), 100)
            if not name or any(a['name'] == name for a in project['assets']):
                continue
            kind = asset.get('kind')
            project['assets'].append({'id': uid(), 'name': name, 'kind': kind if kind in ('scene', 'character', 'prop') else 'scene',
                                      'prompt': string(asset.get('prompt')), 'image': '', 'voice': ''})
        new_script = string(draft.get('script'), 16000)
        if new_script:
            project['script'] = '\n\n'.join(filter(None, [project['script'], new_script]))[:20000]
        project['draft'] = None
        studio.save(project)
        return web.json_response(project)

    @routes.get('/api/jobs')
    async def list_jobs(request):
        return web.json_response(sorted(studio.jobs.values(), key=lambda job: job['created'], reverse=True))

    @routes.post('/api/projects/{project}/jobs')
    async def queue_jobs(request):
        body = await request.json()
        project = studio.project(request.match_info['project'])
        studio.editable(project['id'])
        kind = body.get('kind')
        if kind in ('video', 'image'):
            require(bool(os.environ.get('JINGLIU_REGION')), '请先通过部署工具确认模型许可并启动工作台。', 409)
        if kind == 'video':
            steps = body.get('steps', 20)
            require(type(steps) is int and 4 <= steps <= 40, '采样步数请使用 4–40 的整数。')
            shots = [studio.find_shot(project, body['shot_id'])] if body.get('shot_id') else [s for s in project['shots'] if s['first'] and not s['clip']]
            require(shots, '没有待生成的镜头。请先选择首帧，或在单镜头页面重新生成。')
            for shot in shots:
                require(shot['first'], '请为镜头设置首帧。')
                studio.media_file(project, shot['first'], IMAGE_EXT)
                if shot['last']:
                    studio.media_file(project, shot['last'], IMAGE_EXT)
                require(shot['prompt'] or shot['visual'], f"请为「{shot['title']}」填写动作提示词。")
            jobs = [studio.enqueue(project, 'video', shot_id=shot['id'], label=shot['title'], steps=steps) for shot in shots]
        elif kind == 'image':
            if body.get('asset_id'):
                asset = next((a for a in project['assets'] if a['id'] == body['asset_id']), None)
                require(asset is not None, '素材不存在。', 404)
                require(asset['prompt'] and not asset['image'], '请为没有图片的素材填写参考图提示词。')
                jobs = [studio.enqueue(project, 'image', asset_id=asset['id'], label=f"{asset['name']} · 参考草图")]
            else:
                shot = studio.find_shot(project, body.get('shot_id'))
                require(not shot['first'] and (shot['visual'] or shot['prompt']), '请为没有首帧的镜头填写画面描述。')
                jobs = [studio.enqueue(project, 'image', shot_id=shot['id'], label=f"{shot['title']} · 首帧草图")]
        elif kind == 'draft':
            brief = string(body.get('brief'), 10000)
            require(brief, '请先输入创意或已有剧本。')
            count, target = int(body.get('count', 5)), int(body.get('seconds', 30))
            require(1 <= count <= 12 and 5 <= target <= 120, '请使用 1–12 镜、5–120 秒。')
            jobs = [studio.enqueue(project, 'draft', label='剧本与分镜草案', options={
                'brief': brief, 'count': count, 'seconds': target, 'model': string(body.get('model'), 200),
            })]
        elif kind == 'export':
            require(project['shots'], '请先创建分镜。')
            options = {'size': body.get('size', '720'), 'subtitles': body.get('subtitles', True) is True,
                       'audio': body.get('audio', 'source'), 'voice': body.get('voice', 'local-zh-female')}
            require(options['size'] in ('720', '1080') and options['audio'] in ('source', 'tts', 'track', 'silent') and options['voice'] in engine.VOICES,
                    '导出选项无效。')
            for shot in project['shots']:
                require(shot['clip'] or shot['first'], f"请先为「{shot['title']}」设置首帧或上传镜头视频。")
                studio.media_file(project, shot['clip'] or shot['first'], VIDEO_EXT if shot['clip'] else IMAGE_EXT)
            if options['audio'] == 'track':
                require(project['track'], '请先上传项目音轨。')
                studio.media_file(project, project['track'], AUDIO_EXT)
            jobs = [studio.enqueue(project, 'export', label=string(body.get('name'), 100) or '短剧成片', options=options)]
        else:
            raise web.HTTPBadRequest(text='任务类型无效。')
        return web.json_response(jobs)

    @routes.post('/api/jobs/{job}/{action:retry|cancel}')
    async def manage_job(request):
        job = studio.jobs.get(request.match_info['job'])
        require(job is not None, '任务不存在。', 404)
        if request.match_info['action'] == 'cancel':
            require(job['state'] == 'queued', '只能取消尚未执行的任务。', 409)
            job.update(state='cancelled', message='已取消')
            studio.save_job(job)
            return web.json_response(job)
        require(job['state'] == 'failed', '只有失败的任务可以重试。', 409)
        studio.editable(job['project_id'])
        project = studio.project(job['project_id'])
        if job['kind'] == 'video':
            shot = studio.find_shot(project, job['shot_id'])
            require(shot['first'], '请重新设置首帧。')
        if job.get('prompt_id'):
            job.update(state='queued', progress=0, message='等待重新检查原任务')
            studio.save_job(job)
            studio.wake.set()
            return web.json_response(job)
        fields = {key: copy.deepcopy(job[key]) for key in ('shot_id', 'asset_id', 'label', 'options') if key in job}
        return web.json_response(studio.enqueue(project, job['kind'], **fields))

    return routes


def app_for(data):
    studio = Studio(data)
    app = web.Application(client_max_size=310 * 1024 * 1024, middlewares=[local_only])
    app.add_routes(api(studio))

    async def lifecycle(app):
        async with ClientSession() as session:
            studio.session = session
            studio.comfy = engine.ComfyEngine(session, data)
            worker = asyncio.create_task(studio.worker())
            try:
                yield
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
                await studio.comfy.release()

    app.cleanup_ctx.append(lifecycle)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='镜流 · AI 短剧工作台')
    parser.add_argument('--port', type=int, default=7861)
    parser.add_argument('--data', type=Path, default=HERE / 'data')
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    app = app_for(args.data.resolve())
    if args.open:
        async def open_page(app):
            loop = asyncio.get_running_loop()
            loop.call_later(0.5, webbrowser.open, f'http://127.0.0.1:{args.port}/')
        app.on_startup.append(open_page)
    web.run_app(app, host='127.0.0.1', port=args.port, access_log=None)
