"""Verify the installed runtime through the public local application endpoints."""
import json
from pathlib import Path
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


def verify(runtime, config, video):
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
                verify_project(base, data, location, video)
            finally:
                stop_owned(process)
                log = data / 'comfy.log'
                if log.is_file():
                    (runtime / 'verify-comfy.log').write_bytes(log.read_bytes())
    label = 'H3 图生视频、应用 API、字幕及 MP4 解码' if video else 'CUDA、应用 API、字幕及定帧 MP4 解码'
    print(f'验证通过 · {label}', flush=True)


def verify_project(base, data, location, video):
    def post(path, payload):
        return read_url(base + path, payload=payload, studio=True, method='POST')

    project = post('/api/sample', {})
    project_path = '/api/projects/' + project['id']
    shot = project['shots'][0]
    post(project_path + '/shots', {'id': shot['id'], 'seconds': 0.75,
                                   'quality': 'quick', 'dialogue': '旁白：收到。'})
    if video:
        jobs = post(project_path + '/jobs', {'kind': 'video', 'shot_id': shot['id']})
        clip = wait_job(base, jobs[0]['id'], 1800)
        path = data / 'projects' / project['id'] / clip['file']
        if not path.is_file() or path.stat().st_size < 1024:
            raise RuntimeError('H3 返回的镜头文件为空。')
    jobs = post(project_path + '/jobs', {'kind': 'export', 'name': '部署验证', 'audio': 'silent', 'subtitles': True})
    export = wait_job(base, jobs[0]['id'], 240)
    output = data / 'projects' / project['id'] / export['file']
    if not output.with_suffix('.srt').is_file():
        raise RuntimeError('导出任务未生成 SRT。')
    exe = str(Path(location) / 'ffmpeg.exe') if location else 'ffmpeg'
    checked(exe, '-v', 'error', '-xerror', '-i', output, '-map', '0:v:0', '-f', 'null', '-')
