#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jingliu CLI 端到端测试：启动 mock 工作台，驱动真实 CLI 子进程，
覆盖全部子命令、错误传播与 --base 连接失败路径。

运行：python tests/test_jingliu_cli.py -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 兼容两种布局：技能自带 tests/ 目录，或主仓库 tests/ 目录
_SCRIPT_CANDIDATES = [
    HERE.parent / 'scripts' / 'jingliu.py',
    HERE.parent / '.agents' / 'skills' / 'jingliu-video' / 'scripts' / 'jingliu.py',
]
SCRIPT = next(p for p in _SCRIPT_CANDIDATES if p.is_file())
MOCK = HERE / 'mock_studio.py'
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'test-image-data'


def start_mock():
    process = subprocess.Popen([sys.executable, str(MOCK), '--port', '0'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    line = process.stdout.readline().decode('utf-8').strip()
    port = json.loads(line)['port']
    return process, f'http://127.0.0.1:{port}'


class CliTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock, cls.base = start_mock()
        cls.tmp = tempfile.mkdtemp(prefix='jingliu-test-')
        cls.png = Path(cls.tmp) / '角色.png'
        cls.png.write_bytes(PNG_BYTES)

    @classmethod
    def tearDownClass(cls):
        cls.mock.terminate()
        cls.mock.wait(timeout=10)
        cls.mock.stdout.close()
        cls.mock.stderr.close()
        shutil.rmtree(cls.tmp)

    def run_cli(self, *args, expect=0, **flags):
        extra = []
        for key, value in flags.items():
            if value is None:
                continue
            extra += [f'--{key.replace("_", "-")}', str(value)]
        result = subprocess.run([sys.executable, str(SCRIPT), *args, *extra, '--base', self.base],
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
        if expect == 0:
            self.assertEqual(result.returncode, 0,
                             f'CLI 应成功。\nargs={args}\nstdout={result.stdout}\nstderr={result.stderr}')
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0,
                            f'CLI 应失败。\nargs={args}\nstdout={result.stdout}')
        self.assertTrue(result.stderr.strip(), f'失败时应输出 stderr。args={args}')
        return result

    def make_project(self, name='测试项目'):
        return self.run_cli('create', '--name', name, '--aspect', '9:16')

    def add_shot(self, pid, **kwargs):
        out = self.run_cli('shot', '--id', pid, '--action', 'add')
        shot_id = out['shots'][-1]['id']
        values = {'title': f'镜头-{shot_id[:6]}', 'visual': '月台上一个小机器人', 'prompt': 'Fixed camera, robot blinks.', 'seconds': 2}
        values.update(kwargs)
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', shot_id, **values)
        return shot_id

    def wait_job(self, job_id, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            response = subprocess.run([sys.executable, str(SCRIPT), 'wait', '--job-id', job_id,
                                       '--interval', '1', '--timeout', str(timeout), '--base', self.base],
                                      capture_output=True, text=True, encoding='utf-8', timeout=timeout + 10)
            self.assertIn(response.returncode, (0, 3, 4), response.stderr)
            job = json.loads(response.stdout)
            self.assertEqual(response.returncode, {'done': 0, 'failed': 3, 'cancelled': 4}[job['state']])
            if job.get('state') in ('done', 'failed', 'cancelled'):
                return job
        self.fail('等待任务超时')


class TestServiceEndpoints(CliTestBase):
    def test_status(self):
        out = self.run_cli('status')
        self.assertTrue(out['comfy'])
        self.assertTrue(out['ollama'])
        self.assertIn('local-zh-female', out['voices'])
        self.assertTrue(out['h3_confirmed'])

    def test_projects_empty_then_list(self):
        self.make_project('列表测试')
        projects = self.run_cli('projects')
        self.assertTrue(any(p['name'] == '列表测试' for p in projects))

    def test_project_get(self):
        created = self.make_project('详情测试')
        detail = self.run_cli('project', '--id', created['id'])
        self.assertEqual(detail['name'], '详情测试')
        self.assertEqual(detail['aspect'], '9:16')

    def test_sample_import(self):
        out = self.run_cli('sample')
        self.assertEqual(out['name'], '月台机器人')
        self.assertTrue(out['shots'])

    def test_connection_error_is_friendly(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'status',
                                 '--base', 'http://127.0.0.1:1'],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertIn('无法连接工作台', result.stderr)
        self.assertIn('打开镜流', result.stderr)


class TestProjectEdit(CliTestBase):
    def test_edit_brief_script_track(self):
        pid = self.make_project()['id']
        upload = self.run_cli('upload', '--id', pid, '--file', str(self.png))
        out = self.run_cli('edit-project', '--id', pid, '--brief', '月台故事', '--script', '第一幕', '--track', upload['file'])
        self.assertEqual(out['brief'], '月台故事')
        self.assertEqual(out['script'], '第一幕')
        self.assertEqual(out['track'], upload['file'])

    def test_track_requires_existing_file(self):
        pid = self.make_project()['id']
        self.run_cli('edit-project', '--id', pid, '--track', 'assets/nope.mp3', expect=1)


class TestAssets(CliTestBase):
    def test_upload_and_asset_lifecycle(self):
        pid = self.make_project()['id']
        upload = self.run_cli('upload', '--id', pid, '--file', str(self.png))
        self.assertTrue(upload['file'].startswith('assets/'))
        # 上传的字节应与原文件一致（multipart 组包正确）
        detail = self.run_cli('project', '--id', pid)
        stored = None
        for category, name in [upload['file'].split('/', 1)]:
            out_file = Path(self.tmp) / 'roundtrip.bin'
            self.run_cli('download', '--id', pid, '--path', f'{category}/{name}', '--out', str(out_file))
            stored = out_file.read_bytes()
        self.assertEqual(stored, PNG_BYTES)
        # 新增素材
        out = self.run_cli('asset', '--id', pid, '--name', '小机器人', '--kind', 'character',
                           '--image', upload['file'], '--prompt', '圆头机器人', '--voice', 'local-zh-female')
        asset = out['assets'][0]
        self.assertEqual(asset['name'], '小机器人')
        # 修改素材
        out = self.run_cli('asset', '--id', pid, '--asset-id', asset['id'], '--name', '机器人一号', '--kind', 'character')
        self.assertEqual(out['assets'][0]['name'], '机器人一号')
        self.assertEqual(out['assets'][0]['image'], upload['file'])
        self.assertEqual(out['assets'][0]['prompt'], '圆头机器人')
        self.assertEqual(out['assets'][0]['voice'], 'local-zh-female')
        # 删除素材
        out = self.run_cli('asset', '--id', pid, '--asset-id', asset['id'], '--remove')
        self.assertFalse(out['assets'])

    def test_asset_voice_validation(self):
        pid = self.make_project()['id']
        self.run_cli('asset', '--id', pid, '--name', '角色', '--kind', 'character',
                     '--voice', 'not-a-voice', expect=1)

    def test_upload_rejects_non_image_image_ext(self):
        bad = Path(self.tmp) / '假图.png'
        bad.write_bytes(b'this is not an image')
        pid = self.make_project()['id']
        self.run_cli('upload', '--id', pid, '--file', str(bad), expect=1)

    def test_upload_missing_file(self):
        pid = self.make_project()['id']
        self.run_cli('upload', '--id', pid, '--file', str(Path(self.tmp) / '不存在.png'), expect=1)


class TestShots(CliTestBase):
    def test_shot_lifecycle(self):
        pid = self.make_project()['id']
        first = self.add_shot(pid, title='A')
        second = self.add_shot(pid, title='B')
        detail = self.run_cli('project', '--id', pid)
        self.assertEqual([s['title'] for s in detail['shots']], ['A', 'B'])
        self.run_cli('shot', '--id', pid, '--action', 'up', '--shot-id', second)
        detail = self.run_cli('project', '--id', pid)
        self.assertEqual([s['title'] for s in detail['shots']], ['B', 'A'])
        self.run_cli('shot', '--id', pid, '--action', 'down', '--shot-id', second)
        self.run_cli('shot', '--id', pid, '--action', 'remove', '--shot-id', second)
        detail = self.run_cli('project', '--id', pid)
        self.assertEqual([s['title'] for s in detail['shots']], ['A'])

    def test_shot_value_validation(self):
        pid = self.make_project()['id']
        shot_id = self.add_shot(pid)
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', shot_id,
                     '--quality', 'ultra', expect=1)
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', shot_id,
                     '--seconds', '99', expect=1)
        # 合法边界：0.5 秒
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', shot_id, '--seconds', '0.5')

    def test_shot_first_requires_existing_file(self):
        pid = self.make_project()['id']
        shot_id = self.add_shot(pid)
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', shot_id,
                     '--first', 'assets/ghost.png', expect=1)


class TestJobs(CliTestBase):
    def test_wait_timeout_and_invalid_interval(self):
        pid = self.make_project()['id']
        uploaded = self.run_cli('upload', '--id', pid, '--file', str(self.png))
        sid = self.add_shot(pid, title='HOLD timeout', first=uploaded['file'])
        job = self.run_cli('video', '--id', pid, '--shot-id', sid)[0]
        response = self.run_cli('wait', '--job-id', job['id'], '--timeout', '0', expect=1)
        self.assertEqual(response.returncode, 124)
        self.assertTrue(json.loads(response.stdout)['timeout'])
        response = self.run_cli('wait', '--job-id', job['id'], '--interval', '0', expect=1)
        self.assertNotIn('Traceback', response.stderr)
        self.run_cli('cancel', '--job-id', job['id'])

    def test_video_requires_first_frame(self):
        pid = self.make_project()['id']
        shot_id = self.add_shot(pid)
        result = self.run_cli('video', '--id', pid, '--shot-id', shot_id, expect=1)
        self.assertIn('首帧', result.stderr)

    def test_video_steps_range(self):
        pid = self.make_project()['id']
        shot_id = self.add_shot(pid)
        upload = self.run_cli('upload', '--id', pid, '--file', str(self.png))
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', shot_id, '--first', upload['file'])
        self.run_cli('video', '--id', pid, '--shot-id', shot_id, '--steps', '50', expect=1)

    def test_video_wait_download_roundtrip(self):
        pid = self.make_project('全链路')['id']
        upload = self.run_cli('upload', '--id', pid, '--file', str(self.png))
        shot_id = self.add_shot(pid, first=None)
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', shot_id, '--first', upload['file'])
        jobs = self.run_cli('video', '--id', pid, '--shot-id', shot_id, '--steps', '4')
        self.assertEqual(len(jobs), 1)
        job = self.wait_job(jobs[0]['id'])
        self.assertEqual(job['state'], 'done')
        detail = self.run_cli('project', '--id', pid)
        clip = detail['shots'][0]['clip']
        self.assertTrue(clip.startswith('renders/'))
        # 重生成本镜头会把旧 clip 归档到 versions
        jobs2 = self.run_cli('video', '--id', pid, '--shot-id', shot_id)
        self.wait_job(jobs2[0]['id'])
        detail = self.run_cli('project', '--id', pid)
        self.assertEqual(len(detail['shots'][0]['versions']), 1)

    def test_batch_video_only_pending(self):
        pid = self.make_project('批量')['id']
        upload = self.run_cli('upload', '--id', pid, '--file', str(self.png))
        with_clip = self.add_shot(pid, title='有片')
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', with_clip, '--first', upload['file'])
        jobs = self.run_cli('video', '--id', pid)
        self.wait_job(jobs[0]['id'])
        without_first = self.add_shot(pid, title='无首帧')
        # 有 clip 的镜头不应再次排队；无首帧的镜头应被跳过并报错
        self.run_cli('video', '--id', pid, expect=1)

    def test_sketch_validation_and_run(self):
        pid = self.make_project('草图')['id']
        shot_id = self.add_shot(pid)
        self.run_cli('sketch', '--id', pid, expect=1)  # 缺少目标参数
        jobs = self.run_cli('sketch', '--id', pid, '--shot-id', shot_id)
        self.wait_job(jobs[0]['id'])
        detail = self.run_cli('project', '--id', pid)
        self.assertTrue(detail['shots'][0]['first'].startswith('assets/'))
        # 已有首帧后再次 sketch 应被拒绝
        self.run_cli('sketch', '--id', pid, '--shot-id', shot_id, expect=1)

    def test_sketch_for_asset(self):
        pid = self.make_project('素材图')['id']
        out = self.run_cli('asset', '--id', pid, '--name', '站长', '--kind', 'character', '--prompt', '中年站长')
        asset_id = out['assets'][0]['id']
        jobs = self.run_cli('sketch', '--id', pid, '--asset-id', asset_id)
        self.wait_job(jobs[0]['id'])
        detail = self.run_cli('project', '--id', pid)
        self.assertTrue(detail['assets'][0]['image'].startswith('assets/'))

    def test_draft_and_apply(self):
        pid = self.make_project('编剧')['id']
        jobs = self.run_cli('draft', '--id', pid, '--brief', '机器人在月台等车', '--count', '3', '--seconds', '20')
        self.wait_job(jobs[0]['id'])
        detail = self.run_cli('project', '--id', pid)
        self.assertTrue(detail['draft'])
        out = self.run_cli('apply-draft', '--id', pid)
        self.assertEqual(len(out['shots']), 2)
        self.assertEqual(out['draft'], None)
        self.assertIn('草案剧本', out['script'])
        # 再次导入应报「暂无草案」
        self.run_cli('apply-draft', '--id', pid, expect=1)

    def test_export_full_pipeline(self):
        pid = self.make_project('导出')['id']
        upload = self.run_cli('upload', '--id', pid, '--file', str(self.png))
        shot_id = self.add_shot(pid)
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', shot_id,
                     '--first', upload['file'], '--dialogue', '小机器人：信号到了！')
        jobs = self.run_cli('export', '--id', pid, '--size', '1080', '--audio', 'tts',
                            '--voice', 'local-zh-female', '--name', '测试成片')
        self.wait_job(jobs[0]['id'])
        detail = self.run_cli('project', '--id', pid)
        self.assertTrue(detail['exports'])
        export = detail['exports'][-1]
        out_mp4 = Path(self.tmp) / '成片.mp4'
        out_srt = Path(self.tmp) / '字幕.srt'
        self.run_cli('download', '--id', pid, '--path', export['file'], '--out', str(out_mp4))
        self.assertEqual(out_mp4.read_bytes(), b'FAKE_EXPORT_MP4')
        self.run_cli('download', '--id', pid, '--path', export['subtitle'], '--out', str(out_srt))
        self.assertIn('台词', out_srt.read_text(encoding='utf-8'))

    def test_export_invalid_options(self):
        pid = self.make_project('导出校验')['id']
        self.run_cli('export', '--id', pid, '--voice', 'unknown-voice', expect=1)
        self.run_cli('export', '--id', pid, '--audio', 'track', expect=1)  # 未上传音轨
        result = subprocess.run([sys.executable, str(SCRIPT), 'export', '--id', pid,
                                 '--size', '4k', '--base', self.base],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertNotEqual(result.returncode, 0)  # argparse choices 拦截

    def test_retry_failed_job(self):
        pid = self.make_project('重试')['id']
        upload = self.run_cli('upload', '--id', pid, '--file', str(self.png))
        shot_id = self.add_shot(pid, title='FORCE_FAIL 首拍')
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', shot_id, '--first', upload['file'])
        jobs = self.run_cli('video', '--id', pid, '--shot-id', shot_id)
        failed = self.wait_job(jobs[0]['id'])
        self.assertEqual(failed['state'], 'failed')
        new_job = self.run_cli('retry', '--job-id', failed['id'])
        done = self.wait_job(new_job['id'])
        self.assertEqual(done['state'], 'done')

    def test_cancel_queued_job(self):
        pid = self.make_project('取消')['id']
        upload = self.run_cli('upload', '--id', pid, '--file', str(self.png))
        first_id = self.add_shot(pid, title='正常跑')
        second_id = self.add_shot(pid, title='HOLD 取消我')
        for sid in (first_id, second_id):
            self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', sid, '--first', upload['file'])
        jobs_hold = self.run_cli('video', '--id', pid, '--shot-id', second_id)     # HOLD：永不执行
        jobs_normal = self.run_cli('video', '--id', pid, '--shot-id', first_id)
        cancelled = self.run_cli('cancel', '--job-id', jobs_hold[0]['id'])
        self.assertEqual(cancelled['state'], 'cancelled')
        self.wait_job(jobs_normal[0]['id'])
        # 已结束的任务不可取消；已取消/已完成的任务不可重试
        self.run_cli('cancel', '--job-id', jobs_normal[0]['id'], expect=1)
        self.run_cli('retry', '--job-id', jobs_hold[0]['id'], expect=1)
        self.run_cli('retry', '--job-id', jobs_normal[0]['id'], expect=1)

    def test_jobs_filter_and_list(self):
        pid = self.make_project('任务列表')['id']
        upload = self.run_cli('upload', '--id', pid, '--file', str(self.png))
        shot_id = self.add_shot(pid)
        self.run_cli('shot', '--id', pid, '--action', 'save', '--shot-id', shot_id, '--first', upload['file'])
        jobs = self.run_cli('video', '--id', pid, '--shot-id', shot_id)
        self.wait_job(jobs[0]['id'])
        all_jobs = self.run_cli('jobs')
        self.assertTrue(any(j['id'] == jobs[0]['id'] for j in all_jobs))
        filtered = self.run_cli('jobs', '--project', pid)
        self.assertTrue(all(j['project_id'] == pid for j in filtered))
        self.assertTrue(filtered)

    def test_download_bad_path(self):
        pid = self.make_project('坏路径')['id']
        self.run_cli('download', '--id', pid, '--path', 'exports/ghost.mp4',
                     '--out', str(Path(self.tmp) / 'x.mp4'), expect=1)
        self.run_cli('download', '--id', pid, '--path', '没有斜杠',
                     '--out', str(Path(self.tmp) / 'y.mp4'), expect=1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
