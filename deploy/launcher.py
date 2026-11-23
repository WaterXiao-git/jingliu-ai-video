"""Lightweight, single-instance supervisor; never imports or loads model weights."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler
import webbrowser

import installer


def workspace_id(data):
    return hashlib.sha256(os.path.normcase(str(data.resolve())).encode('utf-8')).hexdigest()


def identity(url):
    try:
        with build_opener(ProxyHandler({})).open(url + '/api/identity', timeout=0.4) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def instance_lock(path):
    """The OS releases this lock even after a crash; no stale PID guessing."""
    with path.open('a+b') as handle:
        handle.seek(0)
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        acquired = False
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            pass
        try:
            yield acquired
        finally:
            if acquired:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def wait_ready(url, expected, process=None, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if identity(url) == expected:
            return
        if process is not None and process.poll() is not None:
            raise RuntimeError('工作台提前退出，请查看 studio.log。')
        time.sleep(0.1)
    raise RuntimeError('工作台启动超时，请查看 launcher.log 和 studio.log。')


def run(runtime, config, *, browser=True, data=None):
    data = data or runtime / 'studio-data'
    url = f"http://127.0.0.1:{config['ports']['studio']}"
    expected = {'app': 'jingliu', 'workspace': workspace_id(data)}

    def open_browser():
        if browser:
            webbrowser.open(url)

    if identity(url) == expected:
        open_browser()
        return
    with instance_lock(runtime / '.launcher.lock') as owner:
        if not owner:
            wait_ready(url, expected)
            open_browser()
            return
        # Recheck after taking the lock: another launch may have just become ready.
        if identity(url) == expected:
            open_browser()
            return
        installer.check_port(config['ports']['studio'])
        stop = runtime / '.launcher-stop'
        stop.unlink(missing_ok=True)
        started = time.monotonic()
        with (runtime / 'studio.log').open('ab') as log, contextlib.ExitStack() as services:
            command = [config['python'], '-B', str(installer.ROOT / 'studio/studio.py'),
                       '--port', str(config['ports']['studio']), '--data', str(data)]
            process = subprocess.Popen(command, env=installer.studio_environment(runtime, config),
                                       cwd=installer.ROOT, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=installer.NO_WINDOW)
            try:
                wait_ready(url, expected, process)
                print(f'工作台就绪：{time.monotonic() - started:.3f} 秒；{url}', flush=True)
                open_browser()
                # The optional writer must not delay access to the editor.
                try:
                    services.enter_context(installer.start_ollama(runtime, config['ollama_binary'],
                                                                 port=config['ports']['ollama']))
                except (OSError, RuntimeError) as error:
                    print(f'本地编剧未启动，仍可手动制作：{error}', flush=True)
                while process.poll() is None and not stop.exists():
                    time.sleep(0.25)
                if process.poll() not in (None, 0):
                    raise RuntimeError(f'工作台已退出（{process.returncode}），请查看 studio.log。')
            finally:
                installer.stop_owned(process)
                stop.unlink(missing_ok=True)


def request_stop(runtime):
    with instance_lock(runtime / '.launcher.lock') as owner:
        if owner:
            print('此运行目录没有由一键启动器启动的服务。')
            return
        (runtime / '.launcher-stop').touch()


def main():
    parser = argparse.ArgumentParser(description='镜流一键启动器')
    parser.add_argument('--target', type=Path, default=installer.DEFAULT_TARGET)
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    runtime = args.target.resolve()
    # Background launches may have no console. Append also on repeated clicks.
    with contextlib.ExitStack() as logs:
        if not args.no_browser and runtime.is_dir():
            log = logs.enter_context((runtime / 'launcher.log').open('a', encoding='utf-8'))
            logs.enter_context(contextlib.redirect_stdout(log))
            logs.enter_context(contextlib.redirect_stderr(log))
        return execute(args, runtime)


def execute(args, runtime):
    try:
        config = json.loads((runtime / 'runtime.json').read_text(encoding='utf-8'))
        if args.stop:
            request_stop(runtime)
        else:
            run(runtime, config, browser=not args.no_browser)
    except (OSError, ValueError, RuntimeError) as error:
        print(f'镜流启动：{error}', file=sys.stderr, flush=True)
        if os.name == 'nt' and not args.no_browser:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f'{error}\n\n日志目录：{runtime}', '镜流启动失败', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
