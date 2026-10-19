"""Cross-platform runtime regression tests; no model calls."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class NativeRuntimeTests(unittest.TestCase):
    def test_runtime_lock_serializes_processes(self):
        source = ROOT / 'quality-kit' / 'runtime_support.py'
        self.assertTrue(source.exists(), 'portable runtime has not been implemented')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            count = root / 'counter.txt'
            count.write_text('0', encoding='utf-8', newline='\n')
            program = '''import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from runtime_support import file_lock
root = Path(sys.argv[2])
for _ in range(5):
    with file_lock(root / 'counter.lock', timeout=10):
        count = int((root / 'counter.txt').read_text(encoding='utf-8'))
        time.sleep(0.01)
        (root / 'counter.txt').write_text(str(count + 1), encoding='utf-8')
'''
            processes = [subprocess.Popen([sys.executable, '-c', program, str(source.parent), directory]) for _ in range(3)]
            try:
                for process in processes:
                    self.assertEqual(process.wait(timeout=15), 0)
                self.assertEqual(count.read_text(encoding='utf-8'), '15')
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait()


    def test_windows_hook_settings_use_powershell(self):
        source = ROOT / 'quality-kit' / 'runtime_support.py'
        spec = importlib.util.spec_from_file_location('runtime_test', source)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        settings = module.hook_settings(source.parent, windows=True)
        for groups in settings['hooks'].values():
            for group in groups:
                for hook in group['hooks']:
                    self.assertEqual(hook['shell'], 'powershell')
                    self.assertIn('$env:LOCAL_QUALITY_PYTHON', hook['command'])
                    self.assertIn('[Console]::In.ReadToEnd()', hook['command'])
                    self.assertIn('UTF8Encoding', hook['command'])
                    self.assertIn('exit $LASTEXITCODE', hook['command'])

    def test_runner_can_preserve_existing_model_mapping(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            base = [sys.executable, str(ROOT / 'bench.py'), '--runs', directory]
            subprocess.run(base + ['prepare', '--repeats', '1'], check=True, capture_output=True)
            result = subprocess.run(base + ['run', '--id', 'dedupe-baseline-r1', '--inherit-cli-config'], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            dry = json.loads(result.stdout)
            self.assertNotIn('--model', dry['command'])
            self.assertNotIn('--setting-sources', dry['command'])
            self.assertNotIn('--strict-mcp-config', dry['command'])
            self.assertIsNone(dry['isolated_config_dir'])
            self.assertEqual(dry['model_connection'], 'inherited')


    def test_timeout_stops_child_processes(self):
        import time
        spec = importlib.util.spec_from_file_location('runtime_tree_test', ROOT / 'quality-kit' / 'runtime_support.py')
        assert spec is not None and spec.loader is not None
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as directory:
            heartbeat = Path(directory) / 'heartbeat.txt'
            child = "import sys,time; f=open(sys.argv[1], 'a');\nwhile True:\n f.write('x'); f.flush(); time.sleep(0.03)"
            parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]]); time.sleep(30)'
            process = subprocess.Popen([sys.executable, '-c', parent, child, str(heartbeat)], **runtime.process_options())
            try:
                deadline = time.monotonic() + 10
                while not heartbeat.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(heartbeat.exists(), 'grandchild failed to start')
                runtime.stop_process_tree(process)
                time.sleep(0.1)
                size = heartbeat.stat().st_size
                time.sleep(0.15)
                self.assertEqual(heartbeat.stat().st_size, size, 'grandchild survived process tree termination')
            finally:
                if process.poll() is None:
                    runtime.stop_process_tree(process)


if __name__ == '__main__':
    unittest.main(verbosity=2)
