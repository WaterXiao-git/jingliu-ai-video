import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('desktop_build', ROOT / 'desktop/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class DesktopDistribution(unittest.TestCase):
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
