"""Verify the installed runtime through the public local application endpoints."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from installer import LOCAL, assert_packages, checked, ffmpeg_dir, read_url, start, start_ollama, stop_owned, valid_region, wait_for


def wait_job(base, job_id, timeout):
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        job = next(item for item in read_url(base + '/api/jobs') if item['id'] == job_id)
        message = job['message']
        if message != previous:
            print(f"{job['progress']:3}% · {message}", flush=True)
            previous = message
        if job['state'] == 'done':
            return job
        if job['state'] in ('failed', 'cancelled'):
            raise RuntimeError(message)
        time.sleep(4)
    raise RuntimeError('等待测试任务超时。可查看 verify-comfy.log。')


def verify(runtime, config, video, *, video_steps=4):
    if not valid_region(config.get('region')):
        raise RuntimeError('运行配置缺少可用地区声明，请重新确认安装。')
    location = ffmpeg_dir(runtime)
    if location is None:
        raise RuntimeError('FFmpeg 编码器、字幕滤镜或 ffprobe 不可用。')
    assert_packages(Path(config['python']), runtime / 'verify.log')
    with tempfile.TemporaryDirectory(prefix='verify-', dir=runtime) as folder:
        data = Path(folder)
        with start_ollama(runtime, config.get('ollama_binary')):
            process = start(runtime, config, foreground=False, data=data)
            try:
                base = f"http://{LOCAL}:{config['ports']['studio']}"
                status = wait_for(base + '/api/status', process)
                if not status['workflow'] or not status['h3_confirmed']:
                    raise RuntimeError('工作台启动，但工作流或许可配置未加载。')
                if config.get('ollama_binary') and 'qwen2.5:7b' not in status['models']:
                    raise RuntimeError('工作台连不上已安装的 Ollama 7B 模型。')
                evidence = runtime / 'acceptance' / time.strftime('%Y%m%d-%H%M%S')
                evidence.mkdir(parents=True, exist_ok=False)
                if config.get('ollama_binary'):
                    project = read_url(base + '/api/projects', payload={'name': '本地编剧验收', 'aspect': '9:16'}, studio=True, method='POST')
                    route = base + '/api/projects/' + project['id']
                    jobs = read_url(route + '/jobs', payload={'kind': 'draft', 'brief': '小机器人在月台收到信号，微笑着说：收到。只写一个简单镜头。',
                                    'count': 1, 'seconds': 5, 'model': 'qwen2.5:7b'}, studio=True, method='POST')
                    wait_job(base, jobs[0]['id'], 660)
                    drafted = read_url(route)['draft']
                    if not isinstance(drafted.get('shots'), list) or not drafted['shots'] or not drafted.get('script'):
                        raise RuntimeError('编剧模型没有生成可用剧本和分镜。')
                    (evidence / 'draft.json').write_text(json.dumps(drafted, ensure_ascii=False, indent=2), encoding='utf-8')
                    applied = read_url(route + '/apply-draft', payload={}, studio=True, method='POST')
                    if not applied.get('shots') or not applied.get('script'):
                        raise RuntimeError('编剧草案无法导入工作台分镜。')
                    (evidence / 'draft-applied.json').write_text(json.dumps(applied, ensure_ascii=False, indent=2), encoding='utf-8')
                verify_project(base, data, location, video, evidence, video_steps=video_steps)
            finally:
                stop_owned(process)
                log = data / 'comfy.log'
                if log.is_file():
                    (runtime / 'verify-comfy.log').write_bytes(log.read_bytes())
    label = 'H3 图生视频、应用 API、字幕及 MP4 解码' if video else 'CUDA、应用 API、字幕及定帧 MP4 解码'
    print(f'验证通过 · {label}', flush=True)


def verify_project(base, data, location, video, evidence, *, video_steps=4):
    def post(path, payload):
        return read_url(base + path, payload=payload, studio=True, method='POST')

    project = post('/api/sample', {})
    project_path = '/api/projects/' + project['id']
    shot = project['shots'][0]
    post(project_path + '/shots', {'id': shot['id'], 'seconds': 0.75,
                                   'quality': 'quick', 'dialogue': '旁白：收到。'})
    if video:
        print(f'H3 功能验收使用 {video_steps} 步短镜头；正式生成默认 20 步。', flush=True)
        jobs = post(project_path + '/jobs', {'kind': 'video', 'shot_id': shot['id'], 'steps': video_steps})
        clip = wait_job(base, jobs[0]['id'], 3600)
        path = data / 'projects' / project['id'] / clip['file']
        if not path.is_file() or path.stat().st_size < 1024:
            raise RuntimeError('H3 返回的镜头文件为空。')
        shutil.copyfile(path, evidence / 'h3-clip.mp4')
    jobs = post(project_path + '/jobs', {'kind': 'export', 'name': '部署验证', 'audio': 'tts', 'voice': 'local-zh-female', 'subtitles': True})
    export = wait_job(base, jobs[0]['id'], 240)
    output = data / 'projects' / project['id'] / export['file']
    if not output.with_suffix('.srt').is_file():
        raise RuntimeError('导出任务未生成 SRT。')
    exe = str(Path(location) / 'ffmpeg.exe') if location else 'ffmpeg'
    checked(exe, '-v', 'error', '-xerror', '-i', output, '-f', 'null', '-')
    ffprobe = str(Path(location) / 'ffprobe.exe') if location else 'ffprobe'
    metadata = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(output)]))
    if not {'video', 'audio'} <= {stream['codec_type'] for stream in metadata['streams']}:
        raise RuntimeError('成片缺少视频或本地配音流。')
    (evidence / 'media.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copyfile(output, evidence / 'export.mp4')
    shutil.copyfile(output.with_suffix('.srt'), evidence / 'export.srt')
    checked(exe, '-v', 'error', '-i', output, '-ss', '0.4', '-frames:v', '1', evidence / 'frame.png')
    print(f'验收样片与字幕保存在 {evidence}', flush=True)
    (evidence / 'verification.json').write_text(json.dumps({'video_generated': video, 'sampling_steps': video_steps if video else None,
        'video_job_id': clip['id'] if video else None, 'export_job_id': export['id'],
        'scope': 'functional_smoke_test', 'formal_default_sampling_steps': 20}, indent=2), encoding='utf-8')
