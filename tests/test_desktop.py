import hashlib
import importlib.util
import json
import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('desktop_build', ROOT / 'desktop/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class DesktopDistribution(unittest.TestCase):
    def test_icon_preserves_rgba_frames_at_shell_and_taskbar_sizes(self):
        def png(size):
            def chunk(name, raw):
                return struct.pack('>I', len(raw)) + name + raw + struct.pack('>I', zlib.crc32(name + raw))
            # Half transparent, half brand color: losing alpha or RGB must change the frame bytes.
            row = b'\x00' + (b'\x00\x00\x00\x00' * (size // 2)) + (b'\x80\x62\xde\xff' * (size - size // 2))
            return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(row * size)) + chunk(b'IEND', b''))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for size in build.ICON_SIZES:
                (root / f'{size}.png').write_bytes(png(size))
            icon = root / 'logo.ico'; build.write_icon(icon, root)
            raw = icon.read_bytes()
            self.assertEqual(struct.unpack('<HHH', raw[:6]), (0, 1, len(build.ICON_SIZES)))
            frames = []
            for index, size in enumerate(build.ICON_SIZES):
                width, height, _, _, planes, bpp, length, offset = struct.unpack_from('<BBBBHHII', raw, 6 + index * 16)
                self.assertEqual((width or 256, height or 256, planes, bpp), (size, size, 1, 32))
                self.assertEqual(raw[offset:offset + length], png(size))
                frames.append((offset, offset + length))
            self.assertEqual(frames[-1][1], len(raw))
            self.assertTrue(all(frames[i][1] == frames[i + 1][0] for i in range(len(frames) - 1)))

    def test_zip_checkout_without_git_still_has_supported_build_metadata(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(build.source_state(root), (None, None))
            (root / '.git').mkdir()
            with patch.object(build.subprocess, 'check_output', side_effect=FileNotFoundError):
                self.assertEqual(build.source_state(root), (None, None))

    def fixture(self, root):
        for name in build.FILES:
            file = root / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(b'source')
        for name in ('deploy/installer.py', 'deploy/vendor/source.zip', 'deploy/acceptance_guard/sitecustomize.py',
                     'studio/web/app.js', 'scripts/queue_run.py'):
            file = root / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(b'public code')

    def test_personal_data_weights_and_nested_runtimes_are_excluded(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            secrets = ('.runtime/runtime.json', 'studio/data/project.json', 'deploy/.env',
                       'deploy/.runtime/runtime.json', 'deploy/downloads/private.json',
                       'deploy/models/weights.safetensors', 'studio/web/.hidden/token.json',
                       'deploy/vendor/models/model.gguf')
            for name in secrets:
                file = root / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(b'private')
            archive = root / 'payload.zip'; build.build_payload(archive, root)
            with ZipFile(archive) as zip:
                names = set(zip.namelist())
                self.assertTrue(names.isdisjoint(secrets), names.intersection(secrets))
                self.assertIn('deploy/vendor/source.zip', names)
                self.assertIn('deploy/acceptance_guard/sitecustomize.py', names)
                self.assertIn('studio/web/app.js', names)

    def test_payload_is_deterministic_and_each_file_has_correct_digest(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            first = root / 'first.zip'; second = root / 'second.zip'
            self.assertEqual(build.build_payload(first, root), build.build_payload(second, root))
            with ZipFile(first) as zip:
                manifest = json.loads(zip.read('payload-manifest.json'))
                self.assertEqual(set(manifest), set(zip.namelist()) - {'payload-manifest.json'})
                for name, digest in manifest.items():
                    self.assertEqual(hashlib.sha256(zip.read(name)).hexdigest(), digest)

    def test_real_distribution_contains_required_runtime_assets(self):
        names = {p.relative_to(ROOT).as_posix() for p in build.payload_files()}
        self.assertTrue({'studio/engine.py', 'studio/local_speech.ps1', 'studio/demo/robot.png',
                         'docs/MINIMAX-H3-LICENSE.txt', 'LICENSE', 'NOTICE.md',
                         'scripts/queue_run.py', 'workflows/MiniMax_H3_FL2VA_audio.json',
                         'deploy/acceptance_guard/sitecustomize.py', 'deploy/qwen2.5.Modelfile',
                         'deploy/vendor/ComfyUI-783ab7282af1.zip'} <= names)
        self.assertTrue(all(p.is_file() for p in build.payload_files()))


if __name__ == '__main__':
    unittest.main()
