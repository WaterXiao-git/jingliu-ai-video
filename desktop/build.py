"""Build a single Windows EXE using the inbox C# compiler and stdlib only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.5-preview.1'
# Explicit distribution roots: never scoop up an installed runtime or user files.
INCLUDE = ('deploy', 'deploy/vendor', 'deploy/acceptance_guard', 'studio/web', 'studio/demo', 'workflows', 'scripts')
EXTENSIONS = {'.py', '.ps1', '.yaml', '.txt', '.json', '.js', '.css', '.html', '.png', '.zip', '.modelfile'}
FILES = ('studio/studio.py', 'studio/engine.py', 'studio/local_speech.ps1', 'README.md',
         'LICENSE', 'NOTICE.md', 'docs/assets/jingliu-logo.png', 'docs/installation.md',
         'docs/startup.md', 'docs/desktop.md', 'docs/MINIMAX-H3-LICENSE.txt', '打开镜流.cmd')


def payload_files(root=ROOT):
    paths = {root / name for name in FILES}
    for directory in INCLUDE:
        candidates = (root / directory).glob('*') if directory == 'deploy' else (root / directory).rglob('*')
        paths.update(p for p in candidates if p.is_file() and p.suffix.lower() in EXTENSIONS
                     and not any(part.startswith('.') or part in ('__pycache__', 'models', 'projects', 'downloads', 'data', 'runtime')
                                 for part in p.relative_to(root).parts))
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def build_payload(destination, root=ROOT):
    manifest = {}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'w') as archive:
        for path in payload_files(root):
            if path.is_symlink():
                raise RuntimeError(f'打包路径不允许符号链接：{path}')
            raw = path.read_bytes()
            name = path.relative_to(root).as_posix()
            manifest[name] = hashlib.sha256(raw).hexdigest()
            entry = ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, raw)
        entry = ZipInfo('payload-manifest.json', (2020, 1, 1, 0, 0, 0))
        entry.compress_type = ZIP_DEFLATED
        archive.writestr(entry, json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode('utf-8'))
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def source_state(root=ROOT):
    if not (root / '.git').exists():
        return None, None
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True, stderr=subprocess.DEVNULL).strip())
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('EXE 构建需要 Windows；用户运行 EXE 不需要 Python。')
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise RuntimeError('缺少 Windows .NET Framework C# 编译器。')
    stage = ROOT / 'build/desktop'
    stage.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    digest = build_payload(stage / 'payload.zip')
    generated = stage / 'BuildInfo.g.cs'
    generated.write_text('namespace Jingliu { internal static class BuildInfo { '
                         f'public const string Version="{VERSION}"; public const string Digest="{digest}";'
                         ' } }', encoding='utf-8')
    icon_script = stage / 'icon.ps1'
    icon_script.write_text('param([string]$Source,[string]$Destination)\n'
                          '$ErrorActionPreference="Stop"\nAdd-Type -AssemblyName System.Drawing\n'
                          '$sourceImage=[Drawing.Image]::FromFile($Source)\n'
                          '$bitmap=[Drawing.Bitmap]::new($sourceImage,[Drawing.Size]::new(64,64))\n'
                          '$icon=[Drawing.Icon]::FromHandle($bitmap.GetHicon())\n'
                          '$output=[IO.File]::Create($Destination)\n'
                          'try{$icon.Save($output)}finally{$output.Dispose();$icon.Dispose();$bitmap.Dispose();$sourceImage.Dispose()}\n',
                          encoding='utf-8-sig')
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                    str(icon_script), '-Source', str(ROOT / 'docs/assets/jingliu-logo.png'),
                    '-Destination', str(stage / 'jingliu.ico')], check=True)
    executable = output / 'Jingliu.exe'
    command = [str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/utf8output',
               '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
               '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll',
               '/reference:System.IO.Compression.FileSystem.dll',
               '/win32icon:' + str(stage / 'jingliu.ico'),
               '/win32manifest:' + str(ROOT / 'desktop/app.manifest'), '/out:' + str(executable),
               '/resource:' + str(stage / 'payload.zip') + ',Jingliu.Payload',
               '/resource:' + str(ROOT / 'docs/assets/jingliu-logo.png') + ',Jingliu.Logo',
               str(ROOT / 'desktop/Launcher.cs'), str(generated)]
    subprocess.run(command, check=True)
    checksum = hashlib.sha256(executable.read_bytes()).hexdigest()
    (output / 'Jingliu.exe.sha256').write_text(f'{checksum}  Jingliu.exe\n', encoding='ascii')
    instructions = (ROOT / 'desktop/README-Windows.txt').read_text(encoding='utf-8')
    (output / 'README-Windows.txt').write_text(instructions, encoding='utf-8-sig')
    bundle = output / ('Jingliu-Windows-x64-' + VERSION + '.zip')
    with ZipFile(bundle, 'w', compression=ZIP_DEFLATED) as archive:
        for name in ('Jingliu.exe', 'Jingliu.exe.sha256', 'README-Windows.txt'):
            archive.write(output / name, name)
    bundle_hash = hashlib.sha256(bundle.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(f'{checksum}  Jingliu.exe\n{bundle_hash}  {bundle.name}\n', encoding='ascii')
    commit, dirty = source_state()
    result = {'version': VERSION, 'file': executable.name, 'bytes': executable.stat().st_size,
              'sha256': checksum, 'payload_sha256': digest, 'source_commit': commit, 'source_dirty': dirty,
              'bundle_file': bundle.name, 'bundle_bytes': bundle.stat().st_size, 'bundle_sha256': bundle_hash}
    (output / 'build-info.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
