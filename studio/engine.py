"""Local model and media adapters for the short drama workbench."""

import asyncio
import contextlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import aiohttp
import edge_tts

ROOT = Path(__file__).resolve().parent.parent
COMFY = Path(os.environ.get('JINGLIU_COMFY', ROOT / 'ComfyUI')).resolve()
COMFY_PORT = int(os.environ.get('JINGLIU_COMFY_PORT', '8193'))
COMFY_URL = f'http://127.0.0.1:{COMFY_PORT}'
OLLAMA = f"http://127.0.0.1:{int(os.environ.get('JINGLIU_OLLAMA_PORT', '11434'))}"
WORKFLOW = Path(os.environ.get('JINGLIU_WORKFLOW', ROOT / 'workflows/MiniMax_H3_FL2VA_audio.json')).resolve()
FPS = 24
VOICES = {
    'zh-CN-XiaoxiaoNeural': '晓晓 · 青年女声',
    'zh-CN-XiaoyiNeural': '晓伊 · 活泼女声',
    'zh-CN-YunxiaNeural': '云夏 · 少年男声',
    'zh-CN-YunxiNeural': '云希 · 青年男声',
    'zh-CN-YunjianNeural': '云健 · 沉稳男声',
}
sys.path.insert(0, str(ROOT / 'scripts'))
import queue_run


async def command(*args, cwd=None):
    process = await asyncio.create_subprocess_exec(
        *map(str, args), cwd=cwd, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    try:
        output, errors = await process.communicate()
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(errors.decode('utf-8', 'replace').strip()[-2500:] or f'{args[0]} 退出码 {process.returncode}')
    return output


async def probe(path):
    return json.loads(await command('ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path))


async def request_json(session, url, payload=None, timeout=10):
    async with session.request('GET' if payload is None else 'POST', url, json=payload,
                               timeout=aiohttp.ClientTimeout(total=timeout)) as response:
        if response.status >= 400:
            raise RuntimeError(f'HTTP {response.status} · {(await response.text())[:1600]}')
        return await response.json()


async def service_info(session, url):
    try:
        return await request_json(session, url, timeout=2)
    except (aiohttp.ClientError, TimeoutError, RuntimeError, ValueError):
        return None


async def draft(session, project, model, brief, count, seconds):
    catalog = await service_info(session, OLLAMA + '/api/tags')
    names = {item['name'] for item in (catalog or {}).get('models', [])}
    if model not in names:
        raise RuntimeError('请先启动 Ollama，并在剧本页选择已安装的模型。')
    prompt = f'''你是中文短剧编剧和分镜师。根据输入写一集能拍成短视频的脚本。
项目名：{project['name']}。画幅：{project['aspect']}。
约 {seconds} 秒，恰好 {count} 个镜头，每镜 1 至 10 秒。台词简短，按“角色：台词”逐行，允许无台词。
只输出 JSON 对象。字段 title（标题），script（完整中文剧本），assets（数组，每项 kind 为 character 或 scene，name 为名字，prompt 为中文参考图描述），shots（数组，每项 title, seconds, visual 中文画面与动作, prompt 详细英文图生视频提示词, dialogue 中文台词）。
以具体镜头、可见动作和连贯的角色外形为主。台词必须在镜头时长内读完。无需 Markdown。
创作输入如下：
{brief}'''
    result = await request_json(session, OLLAMA + '/api/generate', {
        'model': model, 'prompt': prompt, 'stream': False, 'format': 'json',
        'keep_alive': 0, 'options': {'temperature': 0.5, 'num_ctx': 4096, 'num_predict': 3200},
    }, timeout=600)
    try:
        output = json.loads(result['response'])
        if not isinstance(output['shots'], list) or not output['shots']:
            raise ValueError('没有分镜')
        return output
    except (ValueError, TypeError, KeyError) as error:
        raise RuntimeError('模型没有返回可用分镜。请缩短输入或减少镜头数量后重试。') from error


class ComfyEngine:
    def __init__(self, session, data):
        self.session = session
        self.data = data
        self.process = None
        self.input_dir = data / 'comfy' / 'input'
        self.output_dir = data / 'comfy' / 'output'
        self.user_dir = data / 'comfy' / 'user'

    async def ensure(self, update):
        live = await service_info(self.session, COMFY_URL + '/system_stats')
        if live is not None:
            if self.process is not None and self.process.poll() is None:
                return
            raise RuntimeError(f'端口 {COMFY_PORT} 已被另一个 ComfyUI 占用，请关闭它后重试。')
        if not WORKFLOW.is_file() or not (COMFY / 'main.py').is_file():
            raise RuntimeError('找不到本地 ComfyUI 或 H3 工作流。')
        if self.process is None or self.process.poll() is not None:
            temp = self.data / 'tmp'
            temp.mkdir(exist_ok=True)
            for directory in (self.input_dir, self.output_dir, self.user_dir):
                directory.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, TEMP=str(temp), TMP=str(temp), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
            with (self.data / 'comfy.log').open('ab') as log:
                self.process = subprocess.Popen(
                    [sys.executable, 'main.py', '--lowvram', '--fp16-vae', '--disable-pinned-memory', '--disable-auto-launch',
                     '--input-directory', str(self.input_dir), '--output-directory', str(self.output_dir),
                     '--temp-directory', str(temp), '--user-directory', str(self.user_dir),
                     '--listen', '127.0.0.1', '--port', str(COMFY_PORT)], cwd=COMFY, env=env,
                    stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
        for attempt in range(60):
            update(2, f'正在启动 ComfyUI · {attempt * 2} 秒')
            if await service_info(self.session, COMFY_URL + '/system_stats') is not None:
                return
            if self.process.poll() is not None:
                raise RuntimeError('ComfyUI 启动失败。请查看工作台数据目录中的 comfy.log。')
            await asyncio.sleep(2)
        raise RuntimeError('ComfyUI 启动超时。请查看工作台数据目录中的 comfy.log。')

    async def watch(self, socket, prompt_id, update):
        async for message in socket:
            if message.type != aiohttp.WSMsgType.TEXT:
                continue
            event = message.json()
            data = event.get('data', {})
            if data.get('prompt_id') != prompt_id:
                continue
            if event.get('type') == 'progress' and data.get('max'):
                fraction = data['value'] / data['max']
                update(12 + min(fraction, 1) * 75, f"模型采样 {data['value']}/{data['max']}")
            elif event.get('type') == 'executing' and str(data.get('node')) in ('14', '15', '16', '21'):
                update(90, '正在解码和写出镜头')

    async def video(self, project_dir, project, shot, job, update):
        await self.ensure(update)
        client = job.get('client_id') or uuid.uuid4().hex
        prompt_id = job.get('prompt_id')
        if not prompt_id:
            portrait = project['aspect'] == '9:16'
            sizes = {'quick': (320, 576), 'normal': (480, 864), 'detail': (768, 1344)}
            width, height = sizes[shot['quality']]
            if not portrait:
                width, height = height, width
            frames = max(22, 5 + 17 * math.ceil((math.ceil(shot['seconds'] * FPS) - 5) / 17))
            queue_run.WORKFLOW = str(WORKFLOW)
            queue_run.SERVER = COMFY_URL
            update(7, '准备参考图与 H3 工作流')
            overrides = {'11.steps': 20, '12.noise_seed': shot['seed'] if shot['seed'] is not None else random.randrange(2**32),
                         '8.width': width, '8.height': height, '8.length': frames,
                         '8.prompt': shot['prompt'] or shot['visual'],
                         '16.filename_prefix': f"video/drama_studio/{job['id']}/shot"}
            if shot['first']:
                folder = self.input_dir / 'drama_studio' / job['id']
                folder.mkdir(parents=True, exist_ok=True)
                for node, name, relative in [(17, 'first', shot['first']), (18, 'last', shot['last'] or shot['first'])]:
                    source = project_dir / relative
                    target = folder / (name + source.suffix.lower())
                    shutil.copyfile(source, target)
                    overrides[f'{node}.image'] = target.relative_to(self.input_dir).as_posix()
            try:
                graph = await asyncio.to_thread(queue_run.build_api_prompt, overrides)
            except SystemExit as error:
                raise RuntimeError(str(error)) from error
            if not shot['first']:
                for key in ('first_frame', 'last_frame'):
                    graph['8']['inputs'].pop(key, None)
                graph.pop('17', None)
                graph.pop('18', None)
        async with self.session.ws_connect(COMFY_URL.replace('http:', 'ws:') + '/ws?clientId=' + client) as socket:
            if not prompt_id:
                response = await request_json(self.session, COMFY_URL + '/prompt', {'prompt': graph, 'client_id': client}, 60)
                prompt_id = response['prompt_id']
                job['prompt_id'] = prompt_id
                job['client_id'] = client
            update(10, '已送入 ComfyUI 队列')
            watcher = asyncio.create_task(self.watch(socket, prompt_id, update))
            try:
                start = time.monotonic()
                while time.monotonic() - start < 10800:
                    history = await request_json(self.session, f'{COMFY_URL}/history/{prompt_id}', timeout=30)
                    entry = history.get(prompt_id)
                    if entry:
                        status = entry.get('status', {})
                        if status.get('status_str') == 'error':
                            errors = [info.get('exception_message', kind) for kind, info in status.get('messages', [])
                                      if kind in ('execution_error', 'execution_interrupted')]
                            job.pop('prompt_id', None)
                            raise RuntimeError('H3 生成失败 · ' + (' / '.join(errors) or '请查看 ComfyUI 日志'))
                        if status.get('completed'):
                            source = self.video_output(entry)
                            if job['kind'] == 'image':
                                update(95, '从短片中提取参考图')
                                relative = f"assets/{job['id']}.png"
                                await command('ffmpeg', '-v', 'error', '-y', '-ss', '0.375', '-i', source,
                                              '-frames:v', '1', '-threads', '1', project_dir / relative)
                            else:
                                relative = f"renders/{job['id']}.mp4"
                                shutil.copyfile(source, project_dir / relative)
                            return relative
                    await asyncio.sleep(4)
                raise RuntimeError('生成等待超过 3 小时。重试会继续检查同一个 ComfyUI 任务。')
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)

    def video_output(self, entry):
        base = self.output_dir.resolve()
        for node in entry.get('outputs', {}).values():
            for items in node.values():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict) or not item.get('filename', '').lower().endswith('.mp4'):
                        continue
                    source = (base / item.get('subfolder', '') / item['filename']).resolve()
                    if source.is_relative_to(base) and source.is_file():
                        return source
        raise RuntimeError('ComfyUI 任务完成，但没有找到输出 MP4。')

    async def release(self):
        if self.process is None or self.process.poll() is not None:
            return
        queue = await service_info(self.session, COMFY_URL + '/queue')
        if queue is not None and not queue.get('queue_running') and not queue.get('queue_pending'):
            if sys.platform == 'win32':
                with contextlib.suppress(RuntimeError):
                    await command('taskkill', '/PID', self.process.pid, '/T', '/F')
            else:
                self.process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                await asyncio.to_thread(self.process.wait, 5)


def dialogue_lines(text):
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.replace('：', ':', 1).split(':', 1)
        speaker, words = parts if len(parts) == 2 and len(parts[0]) <= 30 else ('旁白', line)
        if words.strip():
            lines.append((speaker.strip(), words.strip()))
    return lines


def stamp(seconds):
    hours, remainder = divmod(round(seconds * 1000), 3600000)
    minutes, remainder = divmod(remainder, 60000)
    whole, ms = divmod(remainder, 1000)
    return f'{hours:02d}:{minutes:02d}:{whole:02d},{ms:03d}'


async def encode(project_dir, project, job, update):
    options = job['options']
    width, height = ((720, 1280) if options['size'] == '720' else (1080, 1920))
    if project['aspect'] == '16:9':
        width, height = height, width
    scratch = project_dir / 'renders' / job['id']
    scratch.mkdir(exist_ok=True)
    voices = {asset['name']: asset.get('voice') or options['voice'] for asset in project['assets'] if asset['kind'] == 'character'}
    clips, captions, audio = [], [], []
    offset = 0.0
    mode = options['audio']
    for index, shot in enumerate(project['shots']):
        clip = shot['clip']
        source = project_dir / (clip or shot['first'])
        frames = round(shot['seconds'] * FPS)
        seconds = frames / FPS
        part = scratch / f'part{index:03d}.mp4'
        update(5 + 70 * index / len(project['shots']), f"正在装配镜头 {index + 1}/{len(project['shots'])} · {shot['title']}")
        input_args = [] if clip else ['-loop', '1', '-framerate', str(FPS)]
        scale = (f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},'
                 f'fps={FPS},setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration={seconds:.6f}')
        await command('ffmpeg', '-v', 'error', '-y', '-filter_threads', '2', *input_args, '-i', source,
                      '-vf', scale, '-an', '-frames:v', frames, '-threads', '2',
                      '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', part)
        clips.append(part)
        lines = dialogue_lines(shot['dialogue'])
        timings = []
        if mode == 'tts' and lines:
            speech = []
            for line_index, (speaker, words) in enumerate(lines):
                path = scratch / f'voice{index:03d}_{line_index:02d}.mp3'
                voice = voices.get(speaker, options['voice'])
                await asyncio.wait_for(edge_tts.Communicate(words, voice).save(str(path)), 90)
                length = float((await probe(path))['format']['duration'])
                speech.append((path, length))
            gap = min(0.1, seconds / (len(lines) * 4))
            window = seconds - gap * (len(lines) + 1)
            speed = max(1, sum(length for _, length in speech) / window)
            if speed > 1.7:
                raise RuntimeError(f'第 {index + 1} 镜台词太长。请延长镜头或缩短台词后重新导出。')
            cursor = gap
            for path, length in speech:
                stop = cursor + length / speed
                audio.append((path, offset + cursor, length, speed))
                timings.append((cursor, stop))
                cursor = stop + gap
        elif mode == 'source' and clip:
            info = await probe(source)
            if any(stream['codec_type'] == 'audio' for stream in info['streams']):
                audio.append((source, offset, seconds, 1))
        if options['subtitles'] and lines:
            if not timings:
                weights = [len(words) for _, words in lines]
                cursor = 0.0
                for weight in weights:
                    stop = cursor + seconds * weight / sum(weights)
                    timings.append((cursor, stop))
                    cursor = stop
            for (_, words), (begin, end) in zip(lines, timings):
                captions.append(f'{len(captions) + 1}\n{stamp(offset + begin)} --> {stamp(offset + end)}\n{words}\n')
        offset += seconds
    (scratch / 'timeline.txt').write_text('\n'.join(f"file '{part.name}'" for part in clips), encoding='ascii')
    (scratch / 'captions.srt').write_text('\n'.join(captions), encoding='utf-8')
    if mode == 'track':
        audio.append((project_dir / project['track'], 0, offset, 1))
    args = ['ffmpeg', '-v', 'error', '-y', '-filter_threads', '2', '-filter_complex_threads', '2',
            '-f', 'concat', '-safe', '1', '-i', 'timeline.txt']
    filters = []
    for i, (path, start, length, speed) in enumerate(audio, 1):
        args += ['-i', str(path)]
        filters.append(f'[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=duration={length:.6f},'
                       f'asetpts=PTS-STARTPTS,atempo={speed:.6f},adelay={round(start * 1000)}:all=1[a{i}]')
    if audio:
        filters.append(''.join(f'[a{i}]' for i in range(1, len(audio) + 1)) +
                       f'amix=inputs={len(audio)}:normalize=0,alimiter=limit=0.95:latency=1,apad[outa]')
        args += ['-filter_complex', ';'.join(filters), '-map', '0:v', '-map', '[outa]', '-c:a', 'aac', '-b:a', '192k']
    else:
        args += ['-map', '0:v', '-an']
    if captions:
        args += ['-vf', "subtitles=captions.srt:force_style='FontName=Microsoft YaHei,FontSize=21,Outline=2,MarginV=28'",
                 '-c:v', 'libx264', '-crf', '19', '-preset', 'fast', '-threads', '2']
    else:
        args += ['-c:v', 'copy']
    update(78, '正在写入字幕和导出 MP4')
    temporary = scratch / 'export.mp4'
    await command(*args, '-t', f'{offset:.6f}', '-movflags', '+faststart', temporary, cwd=scratch)
    info = await probe(temporary)
    duration = float(info['format']['duration'])
    if abs(duration - offset) > 0.15:
        raise RuntimeError(f'导出时长异常，期望 {offset:.2f} 秒，实际 {duration:.2f} 秒。')
    relative = f"renders/{job['id']}.mp4"
    temporary.replace(project_dir / relative)
    if captions:
        shutil.copyfile(scratch / 'captions.srt', project_dir / f"renders/{job['id']}.srt")
    for part in clips:
        part.unlink()
    return relative
