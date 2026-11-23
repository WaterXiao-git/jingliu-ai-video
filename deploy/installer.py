"""Plan, install, verify and launch a local Jingliu runtime."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile

from doctor import GIB, ROOT, SPEC, detect, evaluate, markdown, media_support, python_packages, venv_python
from network import open_resource


DEFAULT_TARGET = ROOT / '.runtime'
LOCAL = '127.0.0.1'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def matches_size(path, item):
    return path.is_file() and any(path.stat().st_size == version['bytes']
                                  for version in [item, *item.get('compatible_files', [])])


def valid_file(path, item):
    if not path.is_file():
        return False
    size = path.stat().st_size
    expected = {version['sha256'] for version in [item, *item.get('compatible_files', [])] if size == version['bytes']}
    return bool(expected) and sha(path) in expected


def write_json(path, value):
    part = path.with_suffix('.tmp')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    part.replace(path)


def checked(*command, env=None, cwd=None, log=None):
    print(f'> {Path(str(command[0])).name} {command[1] if len(command) > 1 else ""}', flush=True)
    with (log.open('ab') if log else contextlib.nullcontext(None)) as output:
        result = subprocess.run(list(map(str, command)), env=env, cwd=cwd, stdout=output, stderr=subprocess.STDOUT if log else None)
    if result.returncode:
        raise RuntimeError(f'{Path(str(command[0])).name} 退出码 {result.returncode}。' +
                           (f' 详情见本地日志 {log}。' if log else ''))


def download(item, destination, allow_replace=False, *, network_log=None):
    if destination.exists():
        if valid_file(destination, item):
            print(f'已校验，复用 {destination.name}', flush=True)
            return destination
        if not allow_replace:
            raise RuntimeError(f'{destination.name} 已存在但校验失败。请检查文件，安装器保留原件。')
        destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + '.part')
    if item.get('bundled'):
        source = (ROOT / item['bundled']).resolve()
        if not source.is_relative_to(ROOT.resolve()) or not valid_file(source, item):
            raise RuntimeError(f'项目内源码包缺失或校验失败: {item["bundled"]}。请完整解压项目后重试。')
        shutil.copyfile(source, part)
        if not valid_file(part, item):
            raise RuntimeError(f'{destination.name} 本地复制校验失败。')
        part.replace(destination)
        print(f'从项目包内复制已校验源码 {destination.name}', flush=True)
        return destination
    position = part.stat().st_size if part.exists() else 0
    if position == item['bytes'] and valid_file(part, item):
        part.replace(destination)
        return destination
    if position >= item['bytes']:
        part.unlink()
        position = 0
    need = item['bytes'] - position
    if shutil.disk_usage(destination.parent).free < need + 512 * 1024**2:
        raise RuntimeError(f'磁盘空间不足，无法保存 {destination.name}。请换盘或腾出空间后重试。')
    headers = {'User-Agent': 'Jingliu-Installer/0.1', 'Accept-Encoding': 'identity'}
    if position:
        headers['Range'] = f'bytes={position}-'
    print(f'下载 {destination.name} · 约 {need / 1e9:.2f} GB 待接收', flush=True)
    with open_resource(Request(item['url'], headers=headers), hosts=SPEC['download_hosts'], audit=network_log) as response:
        if not response.url.startswith('https://'):
            raise RuntimeError('下载地址跳转到了非 HTTPS。')
        if position and response.status == 206:
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
            if not match or tuple(map(int, match.groups())) != (position, item['bytes'] - 1, item['bytes']):
                raise RuntimeError(f'{destination.name} 的服务器续传范围不符。保留 .part，稍后重试。')
            mode = 'ab'
        elif response.status == 200:
            mode, position = 'wb', 0
        else:
            raise RuntimeError(f'下载返回意外的 HTTP 状态 {response.status}。')
        last = time.monotonic()
        with part.open(mode) as output:
            while chunk := response.read(1024 * 1024):
                position += len(chunk)
                if position > item['bytes']:
                    raise RuntimeError(f'{destination.name} 超出清单大小。')
                output.write(chunk)
                if time.monotonic() - last >= 15:
                    print(f'  {position / item["bytes"]:.0%}', flush=True)
                    last = time.monotonic()
    if not matches_size(part, item):
        raise RuntimeError(f'{destination.name} 下载中断。重新运行即可续传。')
    if not valid_file(part, item):
        part.unlink()
        raise RuntimeError(f'{destination.name} SHA-256 不符。已移除失败的临时下载，请从原发布源重试。')
    part.replace(destination)
    return destination


def extract_archive(archive, destination, item, strip_root=False, only=None):
    marker = destination / '.jingliu-source.json'
    if destination.exists():
        if marker.is_file() and json.loads(marker.read_text(encoding='utf-8'))['sha256'] == item['sha256']:
            return
        raise RuntimeError(f'安装目录已存在且不归本安装器管理: {destination}')
    stage = destination.parent / f'.{destination.name}.extract-{os.getpid()}'
    stage.mkdir(parents=True)
    try:
        with ZipFile(archive) as package:
            for info in package.infolist():
                parts = info.filename.replace('\\', '/').rstrip('/').split('/')
                if not parts or any(part in ('', '.', '..') or ':' in part for part in parts):
                    raise RuntimeError(f'压缩包路径无效: {info.filename}')
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise RuntimeError('压缩包包含符号链接。')
                if info.is_dir():
                    continue
                if only is not None:
                    if parts[-1].lower() not in only or len(parts) < 2 or parts[-2] != 'bin':
                        continue
                    parts = [parts[-1]]
                elif strip_root:
                    parts = parts[1:]
                if not parts:
                    raise RuntimeError('压缩包缺少预期目录层级。')
                target = stage.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
        if only is not None and not all((stage / name).is_file() for name in only):
            raise RuntimeError('压缩包缺少 FFmpeg 可执行文件。')
        write_json(stage / marker.name, {'sha256': item['sha256']})
        stage.rename(destination)
    finally:
        if stage.is_dir():
            shutil.rmtree(stage)


def ffmpeg_dir(runtime):
    bundled = runtime / 'ffmpeg'
    if media_support(str(bundled / 'ffmpeg.exe'), str(bundled / 'ffprobe.exe')):
        return str(bundled)
    if media_support():
        return ''
    return None


def package_problem(found):
    if not found or found.get('python', [])[:2] != [3, 11]:
        return '请选择可运行的 Python 3.11 x64 或现有 ComfyUI .venv。'
    packages = found.get('packages', {})
    expected = SPEC['torch']
    if any(packages.get(name) != expected[key] for name, key in
           [('torch', 'version'), ('torchvision', 'torchvision')]):
        return 'PyTorch 或 torchvision 版本与已验证的 CUDA 13.0 组合不符。请选择新装或正确的复用环境。'
    missing = {'aiohttp', 'pillow', 'edge-tts', 'av', 'comfy-kitchen', 'comfy-aimdo'} - packages.keys()
    if missing:
        return '缺少依赖: ' + ', '.join(sorted(missing))
    return None


def prepare_plan(args):
    runtime = args.target.resolve()
    reuse = args.reuse_comfy.resolve() if args.reuse_comfy else None
    model_dir = (reuse or runtime / 'ComfyUI') / 'models'
    missing = [item for item in SPEC['models'] if not matches_size(model_dir / item['target'], item)]
    ffmpeg = ffmpeg_dir(runtime)
    report = detect(runtime, reuse)
    budget = SPEC['budgets']['reuse_runtime_gib' if reuse else 'with_ollama_gib' if args.with_ollama else 'fresh_runtime_gib']
    if not reuse:
        saved = sum(item['bytes'] for item in SPEC['models'] if item not in missing)
        budget = max(5, budget - saved / GIB)
    if reuse and args.with_ollama:
        budget += 10
    assessment = evaluate(report, int(budget * GIB))
    if reuse and (missing or not (reuse / 'main.py').is_file()):
        assessment['can_install'] = False
        assessment['grade'] = 'B'
        assessment['checks'].append({'item': '复用目录', 'actual': len(missing), 'required': '既有模型齐全且 main.py 存在',
                                     'state': 'wait', 'action': '指定已验证环境，或改为新装。'})
    if reuse and (problem := package_problem(report['software'])):
        assessment['can_install'] = False
        if assessment['grade'] == 'A':
            assessment['grade'] = 'B'
        assessment['checks'].append({'item': '复用软件版本', 'actual': report['software']['packages'].get('torch'),
                                     'required': SPEC['torch']['version'], 'state': 'wait', 'action': problem})
    config_path = runtime / 'runtime.json'
    if config_path.is_file():
        previous = json.loads(config_path.read_text(encoding='utf-8'))
        if Path(previous['comfy']).resolve() != (reuse or runtime / 'ComfyUI') or (previous.get('ollama_binary') and not args.with_ollama):
            assessment['can_install'] = False
            assessment['grade'] = 'B'
            assessment['checks'].append({'item': '已有运行目录', 'actual': '已有不同配置', 'required': '相同安装配置或新目录',
                                         'state': 'wait', 'action': '沿用原配置，或另选安装目录。'})
    report['evaluation'] = assessment
    identity = {'target': str(runtime), 'reuse_comfy': str(reuse) if reuse else None,
                'region': args.region, 'with_ollama': args.with_ollama, 'studio_port': args.port,
                'spec_sha256': sha(ROOT / 'deploy/deploy-spec.yaml')}
    download_bytes = sum(item['bytes'] for item in missing) if not reuse else 0
    if ffmpeg is None:
        download_bytes += SPEC['ffmpeg']['bytes']
    if not reuse:
        download_bytes += sum(item['bytes'] for item in SPEC['sources'] if not item.get('bundled'))
    if args.with_ollama:
        download_bytes += SPEC['ollama']['bytes'] + SPEC['ollama']['weights']['bytes']
    return {
        **identity, 'approval': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:12],
        'report': report, 'known_download_bytes_baseline': download_bytes,
        'python_wheel_download_estimate_gib': 0 if reuse else 6,
        'minimum_target_free_bytes': int(budget * GIB), 'ffmpeg_dir': ffmpeg,
        'missing_models': [item['target'] for item in missing],
        'license': SPEC['license']['url'], 'runtime_changes': '安装产物写入目标目录。复用环境只读校验。'
    }


def valid_region(region):
    return bool(re.fullmatch('[A-Z]{2}', region or '') and region not in SPEC['license']['excluded']
                and region not in ('XX', 'ZZ', 'UN', 'AA'))


def assert_packages(python, log=None):
    problem = package_problem(python_packages(python))
    if problem:
        raise RuntimeError(problem)
    checked(python, '-B', '-c',
            "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; "
            "assert torch.version.cuda == '13.0'; x=torch.ones(4,device='cuda'); "
            "assert x.sum().item()==4; print(torch.cuda.get_device_name())", log=log)


@contextlib.contextmanager
def install_lock(runtime):
    # Windows releases the byte-range lock if the installer exits or is interrupted.
    import msvcrt
    with (runtime / '.install.lock').open('a+b') as file:
        if file.tell() == 0:
            file.write(b'0')
            file.flush()
        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError('此目标目录已有安装进程。') from error
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)


def install(args, plan):
    if not plan['report']['evaluation']['can_install']:
        raise RuntimeError('预检未通过，请先按报告调整。')
    if not valid_region(args.region):
        raise RuntimeError('请确认当前使用地区符合 MiniMax H3 许可，例如适用时输入 --region CN。')
    if args.approve is None:
        print('请先阅读 H3 许可并确认在所声明地区具备使用权。输入计划编号后开始安装。')
        if not sys.stdin.isatty():
            raise RuntimeError('请先展示计划并获得用户确认，再传入 --approve 与计划编号。')
        args.approve = input(f"输入 {plan['approval']} 继续: ").strip()
    if args.approve != plan['approval']:
        raise RuntimeError('未确认本次计划。')
    runtime = args.target.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    with install_lock(runtime):
        install_locked(args, plan, runtime)


def install_locked(args, plan, runtime):
    cache = runtime / 'downloads'
    log = runtime / 'install.log'
    scratch = runtime / 'tmp'
    scratch.mkdir(exist_ok=True)
    env = dict(os.environ, TEMP=str(scratch), TMP=str(scratch), TMPDIR=str(scratch), PYTHONUTF8='1',
               PIP_CONFIG_FILE=os.devnull, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
               NO_PROXY='*', HTTP_PROXY='', HTTPS_PROXY='', ALL_PROXY='',
               PYTHONPATH=str(ROOT / 'deploy/acceptance_guard') + os.pathsep + os.environ.get('PYTHONPATH', ''),
               JINGLIU_ACCEPTANCE_AUDIT=os.environ.get('JINGLIU_ACCEPTANCE_AUDIT') or str(runtime / 'pip-domain-audit'))
    if args.reuse_comfy:
        comfy = args.reuse_comfy.resolve()
        python = venv_python(comfy / '.venv')
        for item in SPEC['sources'][1:]:
            if not (comfy / 'custom_nodes' / Path(item['target']).name / '__init__.py').is_file():
                raise RuntimeError(f'复用环境缺少 {Path(item["target"]).name}。')
        assert_packages(python, log)
        for item in SPEC['models']:
            if not valid_file(comfy / 'models' / item['target'], item):
                raise RuntimeError(f'复用环境权重 SHA-256 不符: {item["target"]}')
    else:
        comfy = runtime / 'ComfyUI'
        for item in SPEC['sources']:
            destination = runtime / item['target']
            marker = destination / '.jingliu-source.json'
            if marker.is_file() and json.loads(marker.read_text(encoding='utf-8')).get('sha256') == item['sha256']:
                continue
            archive = download(item, cache / (destination.name + '.zip'), allow_replace=True, network_log=runtime / 'download-network.jsonl')
            extract_archive(archive, destination, item, strip_root=True)
            archive.unlink()
        venv = runtime / 'venv'
        python = venv_python(venv)
        base = python_packages(sys.executable) or {}
        if base.get('python', [])[:2] != [3, 11] or sys.maxsize <= 2**32:
            raise RuntimeError('请用 64 位 Python 3.11 启动安装器。')
        if not python.is_file() or not (venv / 'pyvenv.cfg').is_file():
            checked(sys.executable, '-m', 'venv', venv, env=env, log=log)
        checked(python, '-B', '-c', "import sys; assert getattr(sys, '_jingliu_acceptance_guard', False), 'Distribution guard did not load'",
                env=env, log=log)
        pip = [python, '-m', 'pip', '--isolated', '--disable-pip-version-check', '--log', runtime / 'pip-network.log']
        flags = ['install', '--no-cache-dir', '--only-binary=:all:', '--no-deps']
        lock = ROOT / SPEC['python_lock']
        torch_names = ['torch', 'torchvision', 'torchaudio']
        # Keep CUDA wheels and general Python packages on their separate pinned indexes.
        base_lock = scratch / 'pypi.lock'
        base_lock.write_text('\n'.join(line for line in lock.read_text(encoding='utf-8').splitlines()
                                       if line.split('==', 1)[0] not in torch_names) + '\n', encoding='utf-8')
        checked(*pip, *flags, '--index-url', SPEC['pypi']['index'], '-r', base_lock, env=env, log=log)
        expected = SPEC['torch']
        checked(*pip, *flags, '--index-url', expected['index'], 'torch==' + expected['version'],
                'torchvision==' + expected['torchvision'], 'torchaudio==' + expected['torchaudio'], env=env, log=log)
        checked(*pip, 'check', env=env, log=log)
        assert_packages(python, log)
        for item in SPEC['models']:
            download(item, comfy / 'models' / item['target'], network_log=runtime / 'download-network.jsonl')
    location = plan['ffmpeg_dir']
    if location is None or location == str(runtime / 'ffmpeg'):
        for item in SPEC['ffmpeg']['files']:
            download(item, runtime / 'ffmpeg' / item['target'], network_log=runtime / 'download-network.jsonl')
        location = str(runtime / 'ffmpeg')
    ollama_binary = None
    if args.with_ollama:
        ollama_binary = runtime / 'ollama' / 'ollama.exe'
        item = SPEC['ollama']
        marker = ollama_binary.parent / '.jingliu-source.json'
        if not marker.is_file() or not ollama_binary.is_file() or json.loads(marker.read_text(encoding='utf-8')).get('sha256') != item['sha256']:
            archive = download(item, cache / 'ollama.zip', allow_replace=True, network_log=runtime / 'download-network.jsonl')
            extract_archive(archive, ollama_binary.parent, item)
            archive.unlink()
        with start_ollama(runtime, str(ollama_binary)):
            install_ollama_model(runtime, ollama_binary, log)
    config = {'comfy': str(comfy), 'python': str(python), 'ffmpeg_dir': location,
              'ollama_binary': str(ollama_binary) if ollama_binary else None,
              'region': args.region, 'version': SPEC['version'],
              'ports': {**SPEC['ports'], 'studio': args.port}}
    write_json(runtime / 'runtime.json', config)
    if os.name == 'nt':
        try:
            checked('powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    ROOT / 'deploy/shortcut.ps1', '-Target', runtime)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            print(f'环境已安装，但桌面快捷方式未创建：{error}。可稍后运行 deploy/shortcut.ps1。')
    print('运行环境已就绪。请完成 verify --video，或运行 start 打开工作台。', flush=True)


def read_url(url, timeout=3, *, payload=None, studio=False, method='GET'):
    headers = {'X-Studio-Request': '1'} if studio else {}
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    req = Request(url, data=json.dumps(payload).encode('utf-8') if payload is not None else None, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as response:
        return json.load(response)


def wait_for(url, process, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'服务提前退出，退出码 {process.returncode}。请查看运行目录中的日志。')
        try:
            return read_url(url)
        except (OSError, ValueError):
            time.sleep(1)
    raise RuntimeError('等待本地服务超时，请检查端口和日志。')


def check_port(port):
    with socket.socket() as listener:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind((LOCAL, port))
        except OSError as error:
            raise RuntimeError(f'本地端口 {port} 已占用。请关闭相应服务，或为工作台指定 --port。') from error


def stop_owned(process):
    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW, check=False)
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def install_ollama_model(runtime, binary, log):
    item = SPEC['ollama']
    weights = item['weights']
    # Retain the verified source GGUF. Ollama may create a separate normalized blob.
    env = ollama_environment(runtime)
    blob = Path(env['OLLAMA_MODELS']) / 'blobs' / ('sha256-' + weights['sha256'])
    download(weights, blob, network_log=runtime / 'download-network.jsonl')
    template = (ROOT / item['modelfile']).read_text(encoding='utf-8')
    modelfile = runtime / 'qwen2.5.Modelfile'
    modelfile.write_text(template.replace('__MODEL_PATH__', blob.as_posix()), encoding='utf-8')
    checked(binary, 'create', item['model'], '-f', modelfile, env=env, log=log)


def ollama_environment(runtime):
    model_dir = runtime / 'ollama-models'
    model_dir.mkdir(exist_ok=True)
    return dict(os.environ, OLLAMA_HOST=f"{LOCAL}:{SPEC['ports']['ollama']}",
                OLLAMA_MODELS=str(model_dir), OLLAMA_NO_CLOUD='1', OLLAMA_KEEP_ALIVE='0', OLLAMA_NOPRUNE='1')


@contextlib.contextmanager
def start_ollama(runtime, binary, *, port=None):
    if not binary:
        yield
        return
    port = port or SPEC['ports']['ollama']
    check_port(port)
    with (runtime / 'ollama.log').open('ab') as log:
        env = dict(ollama_environment(runtime), OLLAMA_HOST=f'{LOCAL}:{port}')
        process = subprocess.Popen([binary, 'serve'], env=env, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        try:
            wait_for(f'http://{LOCAL}:{port}/api/version', process)
            yield
        finally:
            stop_owned(process)


def studio_environment(runtime, config):
    path = os.environ.get('PATH', '')
    if config['ffmpeg_dir']:
        path = config['ffmpeg_dir'] + os.pathsep + path
    return dict(os.environ, PATH=path, PYTHONUTF8='1', PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
                JINGLIU_COMFY=config['comfy'], JINGLIU_COMFY_PORT=str(config['ports']['comfy']),
                JINGLIU_OLLAMA_PORT=str(config['ports']['ollama'] if config['ollama_binary'] else 11434),
                JINGLIU_WORKFLOW=str(ROOT / SPEC['workflow']), JINGLIU_REGION=config['region'],
                JINGLIU_COMMUNITY=SPEC['repository'] + ('/issues' if 'gitee.com/' in SPEC['repository'] else '/discussions'))


def start(runtime, config, foreground=True, *, data=None):
    port = config['ports']['studio']
    check_port(port)
    check_port(config['ports']['comfy'])
    command = [config['python'], '-B', str(ROOT / 'studio/studio.py'),
               '--port', str(port), '--data', str(data or runtime / 'studio-data')]
    env = studio_environment(runtime, config)
    if foreground:
        with start_ollama(runtime, config['ollama_binary']):
            return checked(*command, '--open', env=env, cwd=ROOT)
    return subprocess.Popen(command, env=env, cwd=ROOT, creationflags=NO_WINDOW)


def main():
    parser = argparse.ArgumentParser(description='镜流本地部署工具')
    parser.add_argument('action', choices=('plan', 'install', 'start', 'verify', 'status'))
    parser.add_argument('--target', type=Path, default=DEFAULT_TARGET)
    parser.add_argument('--reuse-comfy', type=Path)
    parser.add_argument('--with-ollama', action='store_true', help='安装隔离的 Ollama 和 qwen2.5:7b')
    parser.add_argument('--region', default='', type=str.upper, help='实际使用地区的 ISO 两位代码')
    parser.add_argument('--approve', help='用户已看过并批准的安装计划编号')
    parser.add_argument('--port', type=int, default=SPEC['ports']['studio'])
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--video', action='store_true', help='验证时提交真实 H3 任务')
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        if args.action in ('plan', 'install'):
            if not 1024 <= args.port <= 65535 or args.port in (SPEC['ports']['comfy'], SPEC['ports']['ollama']):
                raise RuntimeError('请选择不同于引擎端口的工作台端口，范围 1024–65535。')
            plan = prepare_plan(args)
            if args.json:
                print_json(plan)
            else:
                print(markdown(plan['report']))
                print(f"\n安装目录 {plan['target']}\n预计已知下载 {plan['known_download_bytes_baseline'] / 1e9:.2f} GB"
                      f" + Python wheels 预算 {plan['python_wheel_download_estimate_gib']} GiB"
                      f"\nH3 许可 {plan['license']}\n计划编号 {plan['approval']}")
            if args.action == 'install':
                install(args, plan)
            return
        runtime = args.target.resolve()
        path = runtime / 'runtime.json'
        if not path.is_file():
            raise RuntimeError('运行环境尚未配置，请先执行 plan 和 install。')
        config = json.loads(path.read_text(encoding='utf-8'))
        if args.action == 'start':
            from launcher import run
            run(runtime, config)
        elif args.action == 'verify':
            from verify import verify
            verify(runtime, config, args.video)
        else:
            port = config['ports']['studio']
            print_json(read_url(f'http://{LOCAL}:{port}/api/status'))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'镜流部署: {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('操作已停止。未完成的模型下载可用原计划继续。', file=sys.stderr)
        sys.exit(130)


if __name__ == '__main__':
    main()
