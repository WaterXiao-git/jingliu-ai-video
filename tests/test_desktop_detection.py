"""Run the real C# discovery logic against isolated filesystem and disk fixtures."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows desktop discovery')
class DesktopDetection(unittest.TestCase):
    def test_existing_fresh_interrupted_and_resource_limited_machines(self):
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        with TemporaryDirectory() as directory:
            executable = Path(directory) / 'detection.exe'
            subprocess.run([str(compiler), '/nologo', '/utf8output', '/reference:System.Web.Extensions.dll',
                            '/out:' + str(executable), str(ROOT / 'desktop/AutoSetup.cs'),
                            str(ROOT / 'tests/desktop_detection.cs')], check=True, capture_output=True)
            result = subprocess.run([str(executable), directory], check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.count('PASS '), 8)


if __name__ == '__main__':
    unittest.main()
