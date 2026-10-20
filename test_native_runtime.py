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
            full_settings = json.loads((Path(directory) / 'dedupe-full-r1' / 'settings.json').read_text(encoding='utf-8'))
            self.assertIs(full_settings.get('disableAllHooks'), False, 'full treatment must explicitly enable hooks')
            baseline_settings = json.loads((Path(directory) / 'dedupe-baseline-r1' / 'settings.json').read_text(encoding='utf-8'))
            self.assertIs(baseline_settings.get('disableAllHooks'), True)


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


    def test_lock_does_not_write_before_acquiring(self):
        spec = importlib.util.spec_from_file_location('runtime_lock_test', ROOT / 'quality-kit' / 'runtime_support.py')
        assert spec is not None and spec.loader is not None
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'empty.lock'
            with runtime.file_lock(lock):
                self.assertEqual(lock.stat().st_size, 0, 'lock files must not require a pre-lock sentinel write')


    def test_dry_run_never_requires_a_claude_installation(self):
        import argparse
        import contextlib
        import io
        from unittest.mock import patch
        import agent_runner
        import bench
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                bench.prepare(runs, 1, 17)
            args = argparse.Namespace(base_url=None, model=None, inherit_cli_config=True, execute=False)
            output = io.StringIO()
            with patch.object(agent_runner, 'find_claude', side_effect=ValueError('only npm claude.cmd exists')) as locate, contextlib.redirect_stdout(output):
                agent_runner.execute(runs / 'dedupe-baseline-r1', args, bench.run_process, bench.write_json)
            self.assertFalse(locate.called, 'dry run must not validate actual Claude installations')
            self.assertIn('dry_run', output.getvalue())
            self.assertFalse((runs / 'dedupe-baseline-r1' / 'execution.json').exists())
            # Real execution must still validate the installation, not silently
            # try to run the unsupported shim after bypassing the dry-run check.
            args.execute = True
            args.allow_ancestor_instructions = True
            with patch.object(agent_runner, 'find_claude', side_effect=ValueError('only npm claude.cmd exists')) as locate:
                with self.assertRaisesRegex(ValueError, 'only npm claude.cmd'):
                    agent_runner.execute(runs / 'dedupe-baseline-r1', args, bench.run_process, bench.write_json)
            self.assertEqual(locate.call_count, 1)


class NpmLaunchTests(unittest.TestCase):
    def test_windows_npm_entrypoints_are_shell_free(self):
        import json
        from unittest.mock import patch
        from platform_support import _runtime as runtime
        with tempfile.TemporaryDirectory(prefix='npm path 한글 & ') as directory:
            root = Path(directory)
            shim = root / 'claude.cmd'
            package = root / 'node_modules' / '@anthropic-ai' / 'claude-code'
            package.mkdir(parents=True)
            node = root / 'node.exe'
            node.touch()
            for entry in ('cli.js', 'bin/claude.exe'):
                with self.subTest(entry=entry):
                    target = package / entry
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
                    (package / 'package.json').write_text(json.dumps({'name': '@anthropic-ai/claude-code', 'bin': {'claude': entry}}), encoding='utf-8')
                    shim.write_text('@"%~dp0\\node_modules\\@anthropic-ai\\claude-code\\' + entry.replace('/', '\\') + '" %*', encoding='utf-8')
                    with patch.object(runtime, 'IS_WINDOWS', True), patch.object(runtime.shutil, 'which', return_value=str(shim)):
                        self.assertEqual(runtime.find_claude(), str(shim))
                        expected = [str(node), str(target)] if entry.endswith('.js') else [str(target)]
                        self.assertEqual(runtime.claude_command(str(shim)), expected)

    def test_benchmark_preserves_npm_prefix_and_inherited_environment(self):
        import argparse
        import contextlib
        import io
        import json
        import os
        from unittest.mock import patch
        import agent_runner
        import bench
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                bench.prepare(runs, 1, 17)
            args = argparse.Namespace(base_url=None, model=None, inherit_cli_config=True, execute=True, allow_ancestor_instructions=True, timeout=30, model_notes='unit fixture')
            prefix = ['C:/Program Files/node.exe', 'C:/npm path/cli.js']
            def fixture_run(command, workspace, output, timeout, env):
                self.assertEqual(command[:2], prefix)
                self.assertEqual(command[2], '-p')
                self.assertNotIn('--model', command)
                self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:19999')
                output.write_text(json.dumps({'type': 'result', 'result': 'unit fixture'}), encoding='utf-8')
                return {'exit_code': 0, 'timed_out': False, 'seconds': 0}
            with patch.object(agent_runner, 'find_claude', return_value='C:/npm/claude.cmd'), patch.object(agent_runner, 'claude_command', return_value=prefix, create=True), patch.object(agent_runner.subprocess, 'run') as version, patch.dict(os.environ, {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:19999'}), contextlib.redirect_stdout(io.StringIO()):
                version.return_value.stdout = 'fixture-version'
                agent_runner.execute(runs / 'dedupe-baseline-r1', args, fixture_run, bench.write_json)
                self.assertEqual(version.call_args.args[0], prefix + ['--version'])

    def test_local_npm_bin_and_dot_relative_entry(self):
        import json
        from unittest.mock import patch
        from platform_support import _runtime as runtime
        with tempfile.TemporaryDirectory() as directory:
            modules = Path(directory) / 'node_modules'
            package = modules / '@anthropic-ai' / 'claude-code'
            package.mkdir(parents=True)
            (package / 'package.json').write_text(json.dumps({'name': '@anthropic-ai/claude-code', 'bin': './cli.js'}), encoding='utf-8')
            target = package / 'cli.js'
            target.touch()
            shim = modules / '.bin' / 'claude.cmd'
            shim.parent.mkdir()
            shim.write_text('@"%~dp0\\..\\@anthropic-ai\\claude-code\\cli.js" %*', encoding='utf-8')
            with patch.object(runtime, 'IS_WINDOWS', True), patch.object(runtime.shutil, 'which', return_value='C:/Node/node.exe'):
                self.assertEqual(runtime.claude_command(str(shim)), ['C:/Node/node.exe', str(target.resolve())])

    def test_npm_missing_node_is_actionable(self):
        import json
        from unittest.mock import patch
        from platform_support import _runtime as runtime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'node_modules' / '@anthropic-ai' / 'claude-code'
            package.mkdir(parents=True)
            (package / 'package.json').write_text(json.dumps({'name': '@anthropic-ai/claude-code', 'bin': {'claude': 'cli.js'}}), encoding='utf-8')
            (package / 'cli.js').touch()
            shim = root / 'claude.cmd'
            shim.write_text('@"%~dp0\\node_modules\\@anthropic-ai\\claude-code\\cli.js" %*', encoding='utf-8')
            with patch.object(runtime, 'IS_WINDOWS', True), patch.object(runtime.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(ValueError, 'Node.js'):
                    runtime.claude_command(str(shim))


if __name__ == '__main__':
    unittest.main(verbosity=2)
