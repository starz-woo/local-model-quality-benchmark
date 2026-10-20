import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hook


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = {'exploration_reminder_after': 2, 'verify_timeout_seconds': 2, 'test_timeout_seconds': 2, 'max_blocked_stops': 1, 'verify_by_suffix': {}, 'test_commands': []}
        self.env = patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(self.root), 'TMPDIR': str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.kit = patch.object(hook, 'KIT', self.root)
        self.kit.start()
        self.addCleanup(self.kit.stop)
        self.write_config()

    def write_config(self):
        (self.root / 'config.json').write_text(json.dumps(self.config), encoding='utf-8', newline='\n')

    def call(self, name, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = hook.handle(dict(hook_event_name=name, session_id='test', **kwargs))
        self.assertEqual(result, 0)
        return json.loads(out.getvalue()) if out.getvalue() else {}

    def edit(self, suffix, content, tool='Edit', expected=None):
        path = self.root / ('file with spaces' + suffix)
        path.write_text(content, encoding='utf-8', newline='\n')
        data = {'file_path': str(path)}
        if expected is not None:
            data['content'] = expected
        return self.call('PostToolUse', tool_name=tool, tool_input=data)

    def test_json_error(self):
        self.assertIn('FAILED', str(self.edit('.json', '{')))

    def test_python_error(self):
        self.assertIn('FAILED', str(self.edit('.py', 'def broken(:')))

    def test_valid_python(self):
        self.assertEqual(self.edit('.py', 'x = 1'), {})

    def test_write_mismatch(self):
        self.assertIn('WRITE VERIFICATION FAILED', str(self.edit('.txt', 'actual', 'Write', 'expected')))

    def test_valid_unicode_write(self):
        self.assertEqual(self.edit('.txt', '한글\n', 'Write', '한글\n'), {})

    def test_exploration_reminder(self):
        self.call('PostToolUse', tool_name='Read')
        self.assertIn('Exploration budget reached', str(self.call('PostToolUse', tool_name='Read')))

    def test_no_tests_is_not_pass(self):
        self.edit('.txt', 'hello')
        self.assertIn('NOT RUN', self.call('Stop')['systemMessage'])

    def test_stop_blocks_and_releases_with_warning(self):
        self.config['test_commands'] = [[sys.executable, '-c', 'import sys; print("failure"); sys.exit(1)']]
        self.write_config()
        self.edit('.txt', 'hello')
        self.assertEqual(self.call('Stop')['decision'], 'block')
        self.assertIn('did NOT pass', self.call('Stop')['systemMessage'])

    def test_stop_success(self):
        self.config['test_commands'] = [[sys.executable, '-c', 'pass']]
        self.write_config()
        self.edit('.txt', 'hello')
        self.assertEqual(self.call('Stop'), {})
        state = json.loads(hook.state_path(self.root, {'session_id': 'test'}).read_text(encoding='utf-8'))
        self.assertFalse(state['dirty'])

    def test_timeout(self):
        ok, output = hook.run_command([sys.executable, '-c', 'import time; time.sleep(5)'], self.root, 0.05)
        self.assertFalse(ok)
        self.assertIn('timed out', output)

    def test_missing_command(self):
        ok, _ = hook.run_command(['nonexistent-quality-tool-123'], self.root, 1)
        self.assertFalse(ok)

    def test_space_argument(self):
        ok, output = hook.run_command([sys.executable, '-c', 'import sys; print(sys.argv[1])', 'a b'], self.root, 2)
        self.assertTrue(ok)
        self.assertIn('a b', output)

    def test_helper_compaction_and_exit(self):
        helper = Path(__file__).with_name('compact_run.py')
        result = subprocess.run([sys.executable, str(helper), '--', sys.executable, '-c', 'import sys; print("X" * 20000); sys.exit(7)'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 7)
        self.assertLess(len(result.stdout), 7000)
        log = Path(next(line.removeprefix('Full log: ') for line in result.stdout.splitlines() if line.startswith('Full log: ')))
        self.addCleanup(log.unlink, missing_ok=True)
        self.assertGreater(log.stat().st_size, 20000)

    def test_hook_command_protocol(self):
        kit = Path(__file__).resolve().parent
        from runtime_support import hook_settings, utf8_environment, IS_WINDOWS
        settings = hook_settings(kit)
        command = settings['hooks']['PostToolUse'][0]['hooks'][0]['command']
        env = dict(utf8_environment(), LOCAL_QUALITY_KIT=str(kit), LOCAL_QUALITY_PYTHON=sys.executable)
        path = self.root / 'broken.json'
        path.write_text('{', encoding='utf-8', newline='\n')
        event = {'hook_event_name': 'PostToolUse', 'session_id': 'protocol', 'tool_name': 'Edit', 'tool_input': {'file_path': str(path)}}
        invocation = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command] if IS_WINDOWS else ['sh', '-c', command]
        result = subprocess.run(invocation, env=env, input=json.dumps(event), capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['hookSpecificOutput']['hookEventName'], 'PostToolUse')
        self.assertIn('FAILED', data['hookSpecificOutput']['additionalContext'])

    def test_launcher_adds_settings_and_preserves_environment(self):
        import launch
        with patch.object(sys, 'argv', ['launch.py', '--model', 'my-local-model']), patch.object(launch, 'find_claude', return_value='/fake/claude', create=True), patch('shutil.which', return_value='/fake/claude'), patch('subprocess.call', return_value=0) as execute:
            launch.main()
        self.assertTrue(execute.called, 'launcher must use a Windows-compatible subprocess rather than execvpe')
        argv = execute.call_args.args[0]
        env = execute.call_args.kwargs['env']
        self.assertEqual(argv[0], '/fake/claude')
        self.assertIn('--settings', argv)
        self.assertIn('--append-system-prompt', argv)
        self.assertEqual(argv[-2:], ['--model', 'my-local-model'])
        self.assertEqual(env['LOCAL_QUALITY_PYTHON'], sys.executable)

    def test_launcher_baseline(self):
        import launch
        with patch.object(sys, 'argv', ['launch.py', '--baseline']), patch.object(launch, 'find_claude', return_value='/fake/claude', create=True), patch('shutil.which', return_value='/fake/claude'), patch('subprocess.call', return_value=0) as execute:
            launch.main()
        self.assertTrue(execute.called)
        self.assertEqual(execute.call_args.args[0], ['/fake/claude'])

    def test_launcher_keeps_npm_command_prefix(self):
        import launch
        prefix = ['C:/Program Files/node.exe', 'C:/npm 한글 & dir/cli.js']
        for flags in ([], ['--baseline']):
            with self.subTest(flags=flags), patch.object(sys, 'argv', ['launch.py'] + flags + ['-p', '한글 " & %PATH% ! ^ | >']), patch.object(launch, 'find_claude', return_value='C:/npm/claude.cmd'), patch.object(launch, 'claude_command', return_value=prefix, create=True), patch('subprocess.call', return_value=7) as execute:
                self.assertEqual(launch.main(), 7)
                self.assertEqual(execute.call_args.args[0][:2], prefix)
                self.assertEqual(execute.call_args.args[0][-2:], ['-p', '한글 " & %PATH% ! ^ | >'])
                self.assertFalse(execute.call_args.kwargs.get('shell', False))

    def test_compact_preserves_ends(self):
        output = hook.compact('START' + 'x' * 10000 + 'END')
        self.assertTrue(output.startswith('START'))
        self.assertTrue(output.endswith('END'))
        self.assertLessEqual(len(output), 6000)


if __name__ == '__main__':
    unittest.main(verbosity=2)
