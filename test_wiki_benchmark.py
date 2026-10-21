"""Offline contract tests; never invoke a model or install packages."""
import ast
from pathlib import Path
import tempfile
import unittest


class WikiTests(unittest.TestCase):
    def test_generated_runtime_compiles_without_executing_generator(self):
        import wiki_adapter
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wiki_adapter.generate(root)
            for path in root.rglob('*.py'):
                compile(path.read_text(encoding='utf-8'), str(path), 'exec')
            source = (root / 'tools/base.py').read_text()
            namespace = {}
            exec(compile(source, 'base.py', 'exec'), namespace)
            registry = namespace['tool_registry']
            @registry.register('example')
            def tool(value):
                return value
            self.assertEqual(registry.get('example')('real'), 'real')
            engine = (root / 'agent/engine.py').read_text()
            self.assertIn('from tools import file_tools, search_tools, sys_tools', engine)
            self.assertIsInstance(ast.parse(engine), ast.Module)
    def test_real_engine_loop_reads_edits_and_dispatches_tools_offline(self):
        import os
        import sys
        from types import ModuleType, SimpleNamespace
        from unittest.mock import MagicMock, patch
        import wiki_adapter
        modules = {}
        for name, attrs in {'openai': ['OpenAI'], 'duckduckgo_search': ['DDGS'],
                            'rich': [], 'rich.console': ['Console'],
                            'rich.syntax': ['Syntax'], 'rich.tree': ['Tree']}.items():
            module = ModuleType(name)
            for attr in attrs:
                setattr(module, attr, MagicMock())
            modules[name] = module
        replies = iter(['<thought>read</thought><read>solution.py</read>',
                        '<thought>edit</thought><edit file="solution.py">def answer(): return 42</edit>',
                        'Finished'])
        def completion(**kwargs):
            return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=next(replies)))])]
        modules['openai'].OpenAI.return_value.chat.completions.create.side_effect = completion
        saved_path, saved_cwd = sys.path[:], Path.cwd()
        # Explicitly execute generated code only inside this test, with external
        # imports mocked. Real AgentEngine/read/edit implementations are exercised.
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, modules):
            root = Path(directory)
            workspace = root / 'workspace'
            workspace.mkdir()
            (workspace / 'solution.py').write_text('broken')
            try:
                os.chdir(workspace)
                for key in list(sys.modules):
                    if key in ('agent', 'tools', 'ui') or key.startswith(('agent.', 'tools.', 'ui.')):
                        del sys.modules[key]
                wiki_adapter.run(root / 'generated', 'Fix it', 'exact-id', 'https://example.invalid/v1', 'fixture-key', 3)
                self.assertEqual((workspace / 'solution.py').read_text(), 'def answer(): return 42\n')
                from tools.base import tool_registry
                self.assertTrue(all(tool_registry.get(tag) for tag in ('read', 'glob', 'lint', 'grep', 'fetch', 'search', 'bash')))
            finally:
                os.chdir(saved_cwd)
                sys.path[:] = saved_path

    def test_windows_opencode_npm_shim_is_resolved_without_cmd_shell(self):
        import platform_support as runtime
        from unittest.mock import patch
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shim = root / 'opencode.cmd'
            package = root / 'node_modules/opencode-ai'
            (package / 'bin').mkdir(parents=True)
            entry = package / 'bin/opencode'
            entry.write_text('// npm entry')
            (package / 'package.json').write_text(json.dumps({'name': 'opencode-ai', 'bin': {'opencode': 'bin/opencode'}}))
            shim.write_text('@node "%dp0%/node_modules/opencode-ai/bin/opencode" %*')
            with patch.object(runtime, 'IS_WINDOWS', True), patch('shutil.which', return_value='C:/node.exe'):
                self.assertEqual(runtime.opencode_command(str(shim)), ['C:/node.exe', str(entry.resolve())])
            (package / 'package.json').write_text(json.dumps({'name': 'opencode-ai', 'bin': {'opencode': '../../escape.js'}}))
            with patch.object(runtime, 'IS_WINDOWS', True), self.assertRaises(ValueError):
                runtime.opencode_command(str(shim))

    def test_timeout_and_launch_failure_are_retained(self):
        import wiki_benchmark as bench
        from unittest.mock import MagicMock, patch
        import subprocess
        child = MagicMock()
        child.communicate.side_effect = [subprocess.TimeoutExpired(['fixture'], 1), ('', '')]
        child.returncode = -9
        with patch('subprocess.Popen', return_value=child), patch.object(bench, 'stop_process_tree') as stop:
            status, code, output = bench.process(['fixture'], '.', {}, 1)
            self.assertEqual((status, code, output), ('timeout', -9, ''))
            stop.assert_called_once_with(child)
        with patch('subprocess.Popen', side_effect=FileNotFoundError):
            self.assertEqual(bench.process(['missing'], '.', {}, 1)[0], 'launch_error')

    def test_config_roots_are_isolated_and_key_not_persisted(self):
        import wiki_benchmark as bench
        from unittest.mock import patch
        import os
        import json
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'OPENCODE_CONFIG': 'user.json', 'OPENCODE_CONFIG_CONTENT': 'user settings'}):
            env = bench.environment(Path(directory), 'private-fixture')
            self.assertNotIn('OPENCODE_CONFIG', env)
            self.assertNotIn('OPENCODE_CONFIG_CONTENT', env)
            self.assertEqual(env['WIKI_BENCH_KEY'], 'private-fixture')
            for name in ('HOME', 'USERPROFILE', 'XDG_CONFIG_HOME', 'APPDATA', 'LOCALAPPDATA'):
                self.assertTrue(Path(env[name]).is_relative_to(Path(directory)))
            self.assertNotIn('private-fixture', json.dumps(bench.config('exact-id', 'https://example.invalid/v1', 10)))
            self.assertFalse(bench.opencode_success('{"type":"error"}\n{"type":"step_finish"}'))
            self.assertFalse(bench.opencode_success(''))
            self.assertTrue(bench.opencode_success('{"type":"step_finish"}'))

    def test_independent_grader_rejects_starter_accepts_reference(self):
        import wiki_benchmark as bench
        from tasks import TASKS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'solution.py').write_text(TASKS['dedupe']['starter'])
            self.assertFalse(bench.grade('dedupe', root))
            (root / 'solution.py').write_text(TASKS['dedupe']['reference'])
            self.assertTrue(bench.grade('dedupe', root))
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['solution.py'])

    def test_dry_run_has_no_external_processes_or_imported_agent(self):
        import wiki_benchmark as bench
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.Popen', side_effect=AssertionError('external IO')):
            self.assertEqual(bench.main(['--output', str(Path(directory) / 'unused')]), 0)
            self.assertFalse((Path(directory) / 'unused').exists())

    def test_counterbalance_repeats_and_failure_reporting(self):
        import wiki_benchmark as bench
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'runs'
            args = bench.parser().parse_args(['--output', str(output), '--model', 'supplied-id',
                '--base-url', 'https://example.invalid/v1', '--repeats', '2', '--tasks', 'dedupe'])
            statuses = iter(['timeout', 'error', 'ok', 'ok'])
            def fake_process(command, cwd, env, timeout):
                status = next(statuses)
                if status == 'ok' and 'grader.py' not in ' '.join(command):
                    from tasks import TASKS
                    (Path(cwd) / 'solution.py').write_text(TASKS['dedupe']['reference'])
                return status, 0 if status == 'ok' else 1, '{"type":"step_finish"}'
            with patch.object(bench, 'process', side_effect=fake_process), patch.object(bench, 'grade', return_value=True):
                rows = bench.execute(args, ['opencode'], 'test-key')
            self.assertEqual([r['agent'] for r in rows], ['wiki', 'opencode', 'opencode', 'wiki'])
            self.assertEqual([r['status'] for r in rows], ['timeout', 'error', 'ok', 'ok'])
            self.assertFalse(rows[0]['passed'])
            self.assertIn('timeout', (output / 'results.csv').read_text())
            self.assertIn('unknown', (output / 'report.md').read_text())
            self.assertEqual(len(list(output.glob('*/workspace/public_test.py'))), 4)


if __name__ == '__main__':
    unittest.main()
