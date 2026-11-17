from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import URLError
from zipfile import BadZipFile, ZipFile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import doctor
import installer


READY = {
    'system': {'os': 'Windows', 'arch': 'AMD64'},
    'gpu': {'adapters': ['NVIDIA RTX'], 'nvidia': [{'vram_mib': 8188, 'free_mib': 7200, 'driver': '617.14'}]},
    'memory': {'total_bytes': 16 * doctor.GIB, 'available_bytes': 6 * doctor.GIB,
               'commit_available_bytes': 25 * doctor.GIB},
    'disk': {'free_bytes': 45 * doctor.GIB},
}


class Compatibility(unittest.TestCase):
    def test_entry_hardware_gets_low_resource_profile(self):
        low = doctor.evaluate(READY)
        self.assertEqual(low['grade'], 'B')
        self.assertTrue(low['can_install'])
        high = deepcopy(READY)
        high['gpu']['nvidia'][0]['vram_mib'] = 16384
        self.assertEqual(doctor.evaluate(high)['grade'], 'A')

    def test_disk_and_busy_gpu_block(self):
        config = deepcopy(READY)
        config['disk']['free_bytes'] = 14 * doctor.GIB
        config['gpu']['nvidia'][0]['free_mib'] = 2500
        result = doctor.evaluate(config)
        self.assertFalse(result['can_install'])
        self.assertEqual(sum(c['state'] == 'wait' for c in result['checks']), 2)
        config['gpu']['nvidia'][0]['free_mib'] = 7300
        self.assertTrue(doctor.evaluate(config, 3 * doctor.GIB)['can_install'])

    def test_missing_driver_evidence_is_unknown(self):
        config = deepcopy(READY)
        config['gpu']['nvidia'] = None
        result = doctor.evaluate(config)
        self.assertEqual(result['grade'], 'C')
        self.assertFalse(result['can_install'])

    def test_below_vram_and_non_nvidia_are_distinguished(self):
        config = deepcopy(READY)
        config['gpu']['nvidia'][0]['vram_mib'] = 6144
        self.assertEqual(doctor.evaluate(config)['grade'], 'D')
        config['gpu'] = {'nvidia': None, 'adapters': ['Intel Graphics']}
        self.assertEqual(doctor.evaluate(config)['grade'], 'D')

    def test_linux_and_apple_doctor_do_not_claim_installer_support(self):
        config = deepcopy(READY)
        for os_name, arch in (('Linux', 'x86_64'), ('Darwin', 'arm64')):
            with self.subTest(os=os_name):
                config['system'] = {'os': os_name, 'arch': arch}
                config['gpu'] = {'nvidia': None, 'adapters': None}
                self.assertFalse(doctor.evaluate(config)['can_install'])

    def test_excluded_regions(self):
        for region in ('US', 'GB', 'DE', 'KR', '', 'ZZ'):
            self.assertFalse(installer.valid_region(region))
        self.assertTrue(installer.valid_region('CN'))

    def test_cpu_torch_is_not_a_compatible_reuse_environment(self):
        found = {'python': [3, 11, 9], 'packages': {'torch': '2.14.1+cpu'}}
        self.assertIn('CUDA', installer.package_problem(found))


class FakeDownload(BytesIO):
    status = 200
    headers = {}
    url = 'https://example.com/models/demo'


class DeploymentFiles(unittest.TestCase):
    raw = b'example-weights'
    item = {'url': 'https://example.com/models/demo', 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}

    def test_resume_and_validate(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'model.safetensors'
            partial = path.with_suffix('.safetensors.part')
            partial.write_bytes(self.raw[:4])
            response = FakeDownload(self.raw[4:])
            response.status = 206
            response.headers = {'Content-Range': f'bytes 4-{len(self.raw)-1}/{len(self.raw)}'}
            with patch.object(installer, 'urlopen', return_value=response) as request:
                installer.download(self.item, path)
            self.assertEqual(request.call_args.args[0].get_header('Range'), 'bytes=4-')
            self.assertEqual(path.read_bytes(), self.raw)
            self.assertFalse(partial.exists())

    def test_interrupted_and_invalid_download_never_replace_good_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'model.safetensors'
            with patch.object(installer, 'urlopen', side_effect=URLError('offline')):
                with self.assertRaises(URLError):
                    installer.download(self.item, path)
            self.assertFalse(path.exists())
            with patch.object(installer, 'urlopen', return_value=FakeDownload(b'X' * len(self.raw))):
                with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                    installer.download(self.item, path)
            self.assertFalse(path.exists())
            path.write_bytes(self.raw)
            with patch.object(installer, 'urlopen', side_effect=AssertionError('must reuse')):
                self.assertEqual(installer.download(self.item, path), path)

    def test_invalid_archive_never_creates_runtime_target(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            target = path / 'ComfyUI'
            archive = path / 'source.zip'
            archive.write_bytes(b'bad archive')
            with self.assertRaises(BadZipFile):
                installer.extract_archive(archive, target, self.item, strip_root=True)
            self.assertFalse(target.exists())
            with ZipFile(archive, 'w') as file:
                file.writestr('fixed-revision/main.py', 'print("example")')
            installer.extract_archive(archive, target, self.item, strip_root=True)
            self.assertTrue((target / 'main.py').is_file())
            self.assertEqual(json.loads((target / '.jingliu-source.json').read_text())['sha256'], self.item['sha256'])


if __name__ == '__main__':
    unittest.main()
