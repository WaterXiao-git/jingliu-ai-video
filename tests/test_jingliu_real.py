"""Exercise the CLI against the production aiohttp routes, without GPU models."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
AVAILABLE = all(importlib.util.find_spec(name) for name in ('aiohttp', 'PIL', 'edge_tts'))


@unittest.skipUnless(AVAILABLE, 'Requires workbench API dependencies')
class RealWorkbench(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp.test_utils import TestClient, TestServer
        sys.path.insert(0, str(ROOT / 'studio'))
        import studio
        self.directory = tempfile.TemporaryDirectory()
        self.app = studio.app_for(Path(self.directory.name))
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.base = str(self.client.make_url('')).rstrip('/')
        self.headers = {'X-Studio-Request': '1'}

    async def asyncTearDown(self):
        await self.client.close()
        self.directory.cleanup()

    async def cli(self, *args):
        process = await asyncio.create_subprocess_exec(sys.executable, '-B', str(ROOT / 'scripts/jingliu.py'),
            *args, '--base', self.base, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
        return process.returncode, json.loads(stdout), stderr.decode('utf-8')

    async def asset(self):
        response = await self.client.post('/api/sample', json={}, headers=self.headers)
        self.assertEqual(response.status, 200)
        project = await response.json()
        return project['id'], project['assets'][0]

    async def test_direct_partial_update_preserves_and_explicit_empty_clears(self):
        pid, before = await self.asset()
        path = f'/api/projects/{pid}/assets'
        response = await self.client.post(path, json={'id': before['id'], 'name': 'renamed'}, headers=self.headers)
        self.assertEqual(response.status, 200)
        after = (await response.json())['assets'][0]
        for key in ('kind', 'image', 'prompt', 'voice'):
            self.assertEqual(after[key], before[key])
        response = await self.client.post(path, json={'id': before['id'], 'image': '', 'prompt': '', 'voice': ''}, headers=self.headers)
        after = (await response.json())['assets'][0]
        self.assertEqual(after['image'], '')
        self.assertEqual(after['prompt'], '')

    async def test_cli_partial_update_and_real_media_download(self):
        pid, before = await self.asset()
        code, project, _ = await self.cli('asset', '--id', pid, '--asset-id', before['id'], '--name', 'cli rename')
        self.assertEqual(code, 0)
        after = project['assets'][0]
        for key in ('kind', 'image', 'prompt', 'voice'):
            self.assertEqual(after[key], before[key])
        out = Path(self.directory.name) / 'new/subfolder/reference.png'
        code, _, _ = await self.cli('download', '--id', pid, '--path', after['image'], '--out', str(out))
        self.assertEqual(code, 0)
        self.assertEqual(out.read_bytes(), (ROOT / 'studio/demo/robot.png').read_bytes())

    async def test_wait_exit_codes_from_real_job_route(self):
        # Persisted terminal jobs; no model generation is submitted.
        for state, expected in (('done', 0), ('failed', 3), ('cancelled', 4)):
            data = Path(self.directory.name)
            await self.client.close()
            job = {'id': 'a' * 32, 'state': state, 'message': 'fixture', 'created': 1}
            (data / 'jobs' / ('a' * 32 + '.json')).write_text(json.dumps(job))
            from aiohttp.test_utils import TestClient, TestServer
            import studio
            self.client = TestClient(TestServer(studio.app_for(data)))
            await self.client.start_server()
            self.base = str(self.client.make_url('')).rstrip('/')
            code, result, _ = await self.cli('wait', '--job-id', job['id'])
            self.assertEqual(code, expected)
            self.assertEqual(result['state'], state)
