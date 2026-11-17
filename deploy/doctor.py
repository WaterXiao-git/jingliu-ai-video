"""Read-only check of the computer running this process."""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GIB = 1024**3
SPEC = json.loads((HERE / 'deploy-spec.yaml').read_text(encoding='utf-8'))


def run_read(*args, timeout=10):
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=timeout, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def read_json(*args, timeout=10):
    try:
        return json.loads(run_read(*args, timeout=timeout) or 'null')
    except ValueError:
        return None


def windows_hardware():
    import ctypes
    from ctypes import wintypes

    class PerformanceInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('committed', 'commit_limit', 'commit_peak',
                'physical_total', 'physical_available', 'system_cache', 'kernel_total',
                'kernel_paged', 'kernel_nonpaged', 'page_size')] + [
            (name, wintypes.DWORD) for name in ('handles', 'processes', 'threads')]

    result = {}
    perf = PerformanceInfo()
    perf.size = ctypes.sizeof(perf)
    if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(perf), perf.size):
        result.update(ram_kib=perf.physical_total * perf.page_size // 1024,
                      free_kib=perf.physical_available * perf.page_size // 1024,
                      commit_limit=perf.commit_limit * perf.page_size,
                      committed=perf.committed * perf.page_size)
    script = ('[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); '
              '$cpu=Get-CimInstance Win32_Processor; $gpu=Get-CimInstance Win32_VideoController; '
              '@{cpu=@($cpu)[0].Name; cores=($cpu|Measure-Object NumberOfCores -Sum).Sum; '
              'gpus=@($gpu|ForEach-Object {$_.Name})}|ConvertTo-Json -Compress')
    result.update(read_json('powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script, timeout=6) or {})
    return result


def linux_hardware():
    try:
        values = dict(re.findall(r'^(\w+):\s+(\d+)', Path('/proc/meminfo').read_text(), re.M))
        cpuinfo = Path('/proc/cpuinfo').read_text()
        cpu = re.search(r'^model name\s*:\s*(.+)$', cpuinfo, re.M)
        names = run_read('lspci')
        adapters = [line.split(': ', 1)[-1] for line in names.splitlines()
                    if any(label in line for label in ('VGA compatible controller', '3D controller', 'Display controller'))] if names else None
        return {'ram_kib': values.get('MemTotal'), 'free_kib': values.get('MemAvailable'),
                'cpu': cpu.group(1) if cpu else None, 'gpus': adapters}
    except OSError:
        return {}


def apple_hardware():
    graphics = read_json('system_profiler', 'SPDisplaysDataType', '-json', timeout=25)
    names = [item.get('sppci_model') or item.get('_name') for item in graphics.get('SPDisplaysDataType', [])] if graphics else None
    ram = numeric(run_read('sysctl', '-n', 'hw.memsize'))
    pressure = run_read('vm_stat') or ''
    page = re.search(r'page size of (\d+) bytes', pressure)
    unused = [int(n) for n in re.findall(r'^Pages (?:free|inactive|speculative):\s+(\d+)', pressure, re.M)]
    return {'ram_kib': ram / 1024 if ram else None, 'free_kib': int(page[1]) * sum(unused) / 1024 if page and unused else None,
            'cpu': run_read('sysctl', '-n', 'machdep.cpu.brand_string'), 'cores': numeric(run_read('sysctl', '-n', 'hw.physicalcpu')),
            'gpus': [name for name in names if name] if names is not None else None}


def numeric(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def in_bytes(value, unit=1):
    value = numeric(value)
    return value * unit if value is not None else None


def nvidia():
    fields = 'name,memory.total,memory.free,driver_version,compute_cap'
    rows = run_read('nvidia-smi', f'--query-gpu={fields}', '--format=csv,noheader,nounits')
    if rows is None:
        fields = 'name,memory.total,memory.free,driver_version'
        rows = run_read('nvidia-smi', f'--query-gpu={fields}', '--format=csv,noheader,nounits')
    if rows is None:
        return None, None
    cards = []
    for row in rows.splitlines():
        columns = [part.strip() for part in row.split(',')]
        if len(columns) not in (4, 5):
            continue
        name, total, free, driver, *cap = columns
        cards.append({'name': name, 'vendor': 'NVIDIA', 'vram_mib': numeric(total),
                      'free_mib': numeric(free), 'driver': driver, 'compute_capability': cap[0] if cap else None})
    header = run_read('nvidia-smi') or ''
    maximum = re.search(r'CUDA Version:\s*([\d.]+)', header)
    return cards, maximum.group(1) if maximum else None


def version_of(*args, pattern=r'\d+(?:\.\d+){1,3}'):
    output = run_read(*args)
    found = re.search(pattern, output or '')
    return found.group() if found else None


def media_support(ffmpeg='ffmpeg', ffprobe='ffprobe'):
    filters = run_read(ffmpeg, '-hide_banner', '-filters') or ''
    encoders = run_read(ffmpeg, '-hide_banner', '-encoders') or ''
    return bool(re.search(r'\bsubtitles\b', filters) and re.search(r'\blibx264\b', encoders)
                and re.search(r'\baac\b', encoders) and version_of(ffprobe, '-version'))


def disk_for(path):
    current = path.resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    try:
        usage = shutil.disk_usage(current)
        return {'total_bytes': usage.total, 'free_bytes': usage.free}
    except OSError:
        return {'total_bytes': None, 'free_bytes': None}


def local_ollama():
    try:
        with urlopen('http://127.0.0.1:11434/api/version', timeout=1.5) as response:
            return json.load(response).get('version')
    except (OSError, ValueError):
        return None


def python_packages(python):
    snippet = """
import json, sys
import importlib.metadata as m
wanted={'torch','torchvision','torchaudio','aiohttp','edge-tts','pillow','av','comfy-kitchen','comfy-aimdo'}
print(json.dumps({'python': list(sys.version_info[:3]), 'packages': {
    name: dist.version for dist in m.distributions()
    if (name := (dist.metadata.get('Name') or '').lower()) in wanted}}))
"""
    return read_json(str(python), '-B', '-c', snippet, timeout=15)


def detect(target, reuse=None):
    system = platform.system()
    arch = platform.machine()
    detectors = {'Windows': windows_hardware, 'Linux': linux_hardware, 'Darwin': apple_hardware}
    local = detectors.get(system, dict)()
    cards, cuda_driver = nvidia() if system != 'Darwin' else (None, None)
    limit, used = numeric(local.get('commit_limit')), numeric(local.get('committed'))
    active_python = Path(sys.executable)
    if reuse:
        active_python = venv_python(reuse / '.venv')
    software = python_packages(active_python) or {}
    toolkit = version_of('nvcc', '--version', pattern=r'(?<=release )\d+\.\d+')
    return {
        'scope': 'host_running_this_command',
        'system': {'os': system, 'edition': local.get('os'), 'release': platform.release(), 'arch': arch},
        'cpu': {'name': local.get('cpu') or platform.processor() or None,
                'cores': numeric(local.get('cores')), 'logical': os.cpu_count()},
        'gpu': {'adapters': local.get('gpus'), 'nvidia': cards,
                'unified_memory': system == 'Darwin' and arch.lower() in ('arm64', 'aarch64')},
        'memory': {'total_bytes': in_bytes(local.get('ram_kib'), 1024), 'available_bytes': in_bytes(local.get('free_kib'), 1024),
                   'commit_available_bytes': max(0, limit - used) if limit and used is not None else None},
        'disk': disk_for(target),
        'software': {'python': software.get('python'), 'packages': software.get('packages', {}),
                     'git': version_of('git', '--version'), 'docker_cli': version_of('docker', '--version'),
                     'cuda_driver_maximum': cuda_driver, 'cuda_toolkit': toolkit,
                     'ffmpeg': version_of('ffmpeg', '-version'), 'ffprobe': version_of('ffprobe', '-version'),
                     'ffmpeg_required_features': media_support() if shutil.which('ffmpeg') and shutil.which('ffprobe') else None,
                     'ollama_service': local_ollama()},
    }


def venv_python(venv):
    return venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def check_network():
    urls = {'pypi': 'https://pypi.org/simple/aiohttp/', 'github': SPEC['sources'][0]['url'],
            'pytorch': SPEC['torch']['index'] + '/torch/', 'huggingface': SPEC['models'][0]['url']}
    results = {}
    for name, url in urls.items():
        try:
            with urlopen(Request(url, method='HEAD'), timeout=7) as response:
                results[name] = response.status
        except HTTPError as error:
            results[name] = error.code
        except (URLError, OSError):
            results[name] = None
    return results


def evaluate(report, budget_bytes=None):
    specs = SPEC['platform']
    checks = []

    def add(item, actual, target, level, action):
        checks.append(dict(item=item, actual=actual, required=target, state=level, action=action,
                           basis='首版支持配置与实测记录，见 deploy-spec.yaml 和 docs/installation.md'))

    system = report['system']
    os_name = system['os']
    supported_arch = system['arch'].lower() in ('amd64', 'x86_64')
    os_level = 'ok' if os_name == 'Windows' and supported_arch else 'unsupported'
    add('安装平台', f"{os_name} / {system['arch']}", 'Windows x64', os_level,
        '可以在本机完成检测。其他平台的安装需另行验证。')
    cards = report['gpu']['nvidia']
    adapters = report['gpu']['adapters']
    if cards:
        # Check the same card's driver and resources together, never combine cards.
        def driver_ok(card):
            version = numeric(str(card.get('driver', '')).split('.')[0])
            return version is not None and version >= specs['driver_major_floor']

        def rank(card):
            return (bool(card.get('vram_mib') and card['vram_mib'] >= specs['minimum_vram_mib'] and driver_ok(card)),
                    bool(card.get('free_mib') and card['free_mib'] >= specs['minimum_free_vram_mib']),
                    card['vram_mib'] is not None, card['vram_mib'] or 0, card['free_mib'] or 0)

        card = max(cards, key=rank)
        total, free = card['vram_mib'], card['free_mib']
        driver = numeric(str(card.get('driver', '')).split('.')[0])
        vram_level = 'unknown' if total is None else 'unsupported' if total < specs['minimum_vram_mib'] else 'ok'
        add('单卡专用显存', total, f"{specs['minimum_vram_mib']} MiB（8GB 级）", vram_level,
            '选择 NVIDIA 单卡。首版不把多卡显存相加。')
        if vram_level == 'ok':
            level = 'unknown' if driver is None else 'wait' if not driver_ok(card) else 'ok'
            add('NVIDIA 驱动', card.get('driver'), f"R{specs['driver_major_floor']} 或兼容版本", level,
                '用 NVIDIA 官方工具更新驱动，再验证 PyTorch CUDA。')
            level = 'unknown' if free is None else 'wait' if free < specs['minimum_free_vram_mib'] else 'ok'
            add('当前空闲显存', free, f"{specs['minimum_free_vram_mib']} MiB 试拍建议", level,
                '关闭你确认可以关闭的 GPU 程序后复检。')
            if total < specs['recommended_vram_mib']:
                add('起步画质', '8–12GB 显存档', '先生成 320×576、22 帧', 'tune', '先试拍，逐步提高分辨率和镜头时长。')
    else:
        has_nvidia = any('nvidia' in name.lower() for name in adapters or [])
        level = 'unknown' if has_nvidia or not (adapters or cards == []) else 'unsupported'
        add('NVIDIA GPU', adapters or None, 'NVIDIA CUDA 独立显卡', level,
            '如有 NVIDIA 显卡，检查驱动和 nvidia-smi。其他 GPU 可使用云端服务。')
    total_ram = report['memory']['total_bytes']
    level = 'unknown' if total_ram is None else 'unsupported' if total_ram < specs['minimum_ram_gib'] * GIB else 'ok'
    add('物理内存', round(total_ram / GIB, 2) if total_ram is not None else None, '16GB 标称，建议 32GB', level,
        '释放内存或增加物理内存。')
    available = report['memory']['available_bytes']
    if available is not None and available < 2 * GIB:
        add('当前可用物理内存', round(available / GIB, 2), '建议至少 2 GiB', 'tune', '可先保存并关闭占用内存较多的应用。')
    commit = report['memory']['commit_available_bytes']
    if os_name == 'Windows':
        level = 'unknown' if commit is None else 'wait' if commit < specs['recommended_commit_gib'] * GIB else 'ok'
        add('Windows 提交余量', round(commit / GIB, 2) if commit is not None else None,
            f"{specs['recommended_commit_gib']} GiB 首次试拍建议", level,
            '释放内存，检查 Windows 页面文件配置后再运行。')
    free = report['disk']['free_bytes']
    budget = budget_bytes if budget_bytes is not None else SPEC['budgets']['fresh_runtime_gib'] * GIB
    level = 'unknown' if free is None else 'wait' if free < budget else 'ok'
    add('目标卷剩余空间', round(free / GIB, 2) if free is not None else None, f'{budget / GIB:.2f} GiB',
        level, '请选择有空间的目标卷，或复用已经校验的环境和模型。')

    states = {check['state'] for check in checks}
    is_no_gpu = any(c['item'] in ('NVIDIA GPU', '单卡专用显存', '物理内存') and c['state'] == 'unsupported' for c in checks)
    grade = 'D' if is_no_gpu else 'C' if states & {'unknown', 'unsupported'} else 'B' if states & {'wait', 'tune'} else 'A'
    return {'grade': grade, 'can_install': not states & {'unknown', 'unsupported', 'wait'}, 'checks': checks}


def markdown(report):
    result = report['evaluation']
    lines = ['# 镜流本机检测报告', '', f"评级 **{result['grade']}** · {'可以制定安装计划' if result['can_install'] else '请按提示调整后复检'}",
             '', '| 项目 | 检测值 | 要求或建议 | 状态 | 下一步 |', '|---|---|---|---|---|']

    def cell(value):
        return ('未知' if value is None else str(value)).replace('|', r'\|').replace('\n', ' ')

    for row in result['checks']:
        lines.append('| ' + ' | '.join(cell(row[field]) for field in ('item', 'actual', 'required', 'state', 'action')) + ' |')
    lines += ['', 'GPU、软件版本和网络探测原始字段可用 --json 查看。']
    if not result['can_install']:
        cards = json.loads((HERE / 'platforms.yaml').read_text(encoding='utf-8'))['platforms']
        lines += ['', '### 云端选项', ''] + [f"- [{card['name']}]({card['url']}) · {card['use']}" for card in cards]
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='镜流本机硬件检查')
    parser.add_argument('--json', action='store_true', help='输出 JSON，不写入文件')
    parser.add_argument('--target', type=Path, default=ROOT / '.runtime', help='计划安装到该目录')
    parser.add_argument('--reuse-comfy', type=Path, help='检查现有 ComfyUI 环境')
    parser.add_argument('--with-ollama', action='store_true')
    parser.add_argument('--network', action='store_true', help='向列出的官方来源发送 HEAD 请求')
    args = parser.parse_args()
    result = detect(args.target, args.reuse_comfy)
    budget = SPEC['budgets']['reuse_runtime_gib' if args.reuse_comfy else 'with_ollama_gib' if args.with_ollama else 'fresh_runtime_gib']
    result['evaluation'] = evaluate(result, budget * GIB)
    result['network'] = check_network() if args.network else None
    if not result['evaluation']['can_install']:
        result['alternatives'] = json.loads((HERE / 'platforms.yaml').read_text(encoding='utf-8'))['platforms']
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else markdown(result))


if __name__ == '__main__':
    main()
