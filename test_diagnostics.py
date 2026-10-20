"""No-model regression tests for observable benchmark execution."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import bench


class DiagnosticTests(unittest.TestCase):
    def test_regular_json_output_is_not_corrupted_by_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output.json'
            program = 'import sys; print("[claude-code:unrecognized_model] warning", file=sys.stderr); print(\'{"type":"result","is_error":false}\')'
            result = bench.run_process([sys.executable, '-c', program], Path(directory), output, 5)
            self.assertEqual(result['exit_code'], 0)
            self.assertFalse(json.loads(output.read_text(encoding='utf-8'))['is_error'])
            self.assertIn('unrecognized_model', output.with_suffix('.stderr.log').read_text(encoding='utf-8'))

    def test_stream_progress_and_final_json_are_separate(self):
        from diagnostics import run_stream_process
        events = [
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 'r1', 'name': 'Read', 'input': {'file_path': 'SECRET_PATH'}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'r1', 'is_error': True, 'content': 'SECRET_ERROR'}]}},
            {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'fixture', 'usage': {'output_tokens': 7}},
        ]
        program = 'import json,sys; print("TELEMETRY_WARNING",file=sys.stderr); events=json.loads(sys.argv[1]); [print(json.dumps(e),flush=True) for e in events]'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'agent-output.json'
            progress = io.StringIO()
            with contextlib.redirect_stderr(progress):
                result = run_stream_process([sys.executable, '-c', program, json.dumps(events)], Path(directory), output, 5)
            self.assertEqual(result['exit_code'], 0)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')), events[-1])
            self.assertEqual(len(output.with_suffix('.events.jsonl').read_text(encoding='utf-8').splitlines()), 3)
            self.assertIn('TELEMETRY_WARNING', output.with_suffix('.stderr.log').read_text(encoding='utf-8'))
            self.assertIn('tool request: Read', progress.getvalue())
            self.assertIn('tool result: Read ERROR', progress.getvalue())
            self.assertIn('final result received', progress.getvalue())
            self.assertNotIn('SECRET', progress.getvalue())

    def test_stream_timeout_keeps_last_tool_stage(self):
        from diagnostics import run_stream_process
        event = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'PowerShell', 'input': {}}]}}
        program = 'import sys,time; print(sys.argv[1],flush=True); time.sleep(30)'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'agent-output.json'
            progress = io.StringIO()
            with contextlib.redirect_stderr(progress):
                result = run_stream_process([sys.executable, '-c', program, json.dumps(event)], Path(directory), output, 1)
            self.assertTrue(result['timed_out'])
            self.assertEqual(result['last_progress'], 'tool request: PowerShell')
            self.assertIn('TIMEOUT', progress.getvalue())
            self.assertEqual(output.read_text(encoding='utf-8'), '')
            self.assertTrue(output.with_suffix('.events.jsonl').is_file())

    def test_stream_without_result_is_not_invented_as_success(self):
        from diagnostics import run_stream_process
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'agent-output.json'
            with contextlib.redirect_stderr(io.StringIO()):
                result = run_stream_process([sys.executable, '-c', 'print("not JSON")'], Path(directory), output, 5)
            self.assertFalse(result['final_result_received'])
            self.assertEqual(output.read_text(encoding='utf-8'), '')

    def test_approval_error_is_labeled_without_echoing_command(self):
        from diagnostics import run_stream_process
        events = [
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 'x', 'name': 'PowerShell'}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'x', 'is_error': True, 'content': 'command contains multiple operations; following part requires approval python -I check_extra.py'}]}},
        ]
        program = 'import sys,json; [print(json.dumps(e),flush=True) for e in json.loads(sys.argv[1])]'
        with tempfile.TemporaryDirectory() as directory:
            progress = io.StringIO()
            with contextlib.redirect_stderr(progress):
                result = run_stream_process([sys.executable, '-c', program, json.dumps(events)], Path(directory), Path(directory) / 'agent-output.json', 5)
            self.assertIn('APPROVAL_REQUIRED', progress.getvalue())
            self.assertEqual(result['approval_error_count'], 1)
            self.assertNotIn('check_extra.py', progress.getvalue())
            self.assertFalse(result['final_result_received'])

    def test_stream_interrupt_stops_the_child(self):
        from diagnostics import run_stream_process, stop_process_tree
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'agent-output.json'
            with patch('diagnostics.queue.Queue.get', side_effect=KeyboardInterrupt), patch('diagnostics.stop_process_tree', wraps=stop_process_tree) as stop, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(KeyboardInterrupt):
                    run_stream_process([sys.executable, '-c', 'import time; time.sleep(30)'], Path(directory), output, 5)
            self.assertEqual(stop.call_count, 1)
            self.assertIsNotNone(stop.call_args.args[0].poll())

    def test_diagnostic_dry_run_builds_stream_flags_without_model_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            base = [sys.executable, str(Path(bench.__file__)), '--runs', directory]
            subprocess.run(base + ['prepare', '--repeats', '1'], check=True, capture_output=True)
            result = subprocess.run(base + ['run', '--id', 'dedupe-baseline-r1', '--inherit-cli-config', '--diagnostics'], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            command = json.loads(result.stdout)['command']
            self.assertEqual(command[command.index('--output-format') + 1], 'stream-json')
            self.assertIn('--verbose', command)
            self.assertFalse(list(Path(directory).glob('*/execution*.json')))

    def test_agent_routes_diagnostics_and_preserves_final_grade_input(self):
        import agent_runner
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                bench.prepare(runs, 1, 17)
            args = argparse.Namespace(base_url=None, model=None, inherit_cli_config=True, execute=True, diagnostics=True, allow_ancestor_instructions=True, timeout=5, model_notes='fixture')
            def fixture_run(command, cwd, output, timeout, env):
                self.assertIn('--verbose', command)
                output.write_text(json.dumps({'type': 'result', 'is_error': False, 'subtype': 'success', 'result': 'fixture'}), encoding='utf-8')
                return {'exit_code': 0, 'timed_out': False, 'seconds': 0}
            with patch.object(agent_runner, 'find_claude', return_value='/fake/claude'), patch.object(agent_runner.subprocess, 'run') as version, patch('diagnostics.run_stream_process', side_effect=fixture_run) as stream, contextlib.redirect_stdout(io.StringIO()):
                version.return_value.stdout = 'fixture'
                agent_runner.execute(runs / 'dedupe-baseline-r1', args, lambda *a, **kw: self.fail('legacy runner used'), bench.write_json)
            self.assertTrue(stream.called)
            record = json.loads((runs / 'dedupe-baseline-r1' / 'execution.json').read_text(encoding='utf-8'))
            self.assertFalse(record['api_error'])
            self.assertTrue(record['diagnostics'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
