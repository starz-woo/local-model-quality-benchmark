"""Offline behavior tests for the MD-only treatment and project deployment."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import bench

ROOT = Path(__file__).resolve().parent


class MinimalTests(unittest.TestCase):
    def test_default_prepare_is_md_only_with_identical_task_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            runs = Path(temporary) / 'runs'
            with contextlib.redirect_stdout(io.StringIO()):
                bench.prepare(runs, 1, 17)
            baseline = runs / 'dedupe-baseline-r1'
            minimal = runs / 'dedupe-minimal-r1'
            self.assertTrue(minimal.is_dir(), 'default treatment must be minimal, not legacy full')
            self.assertFalse((runs / 'dedupe-full-r1').exists())
            for name in ('solution.py', 'TASK.md', 'tests/test_public.py'):
                self.assertEqual((baseline / 'workspace' / name).read_bytes(), (minimal / 'workspace' / name).read_bytes())
            self.assertFalse((baseline / 'workspace/CLAUDE.md').exists())
            self.assertEqual((minimal / 'workspace/CLAUDE.md').read_bytes(), (ROOT / 'minimal-kit/INSTRUCTIONS.md').read_bytes())
            for directory in (baseline, minimal):
                settings = json.loads((directory / 'settings.json').read_text(encoding='utf-8'))
                self.assertTrue(settings['disableAllHooks'])
                self.assertFalse(settings['autoMemoryEnabled'])
                self.assertNotIn('hooks', settings)
                self.assertFalse((directory / 'kit').exists())
            meta = json.loads((minimal / 'meta.json').read_text(encoding='utf-8'))
            self.assertIn('CLAUDE.md', meta['initial_sha256'])
            result = subprocess.run([sys.executable, str(ROOT / 'bench.py'), '--runs', str(runs), 'run', '--id', minimal.name, '--inherit-cli-config'], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            dry = json.loads(result.stdout)
            self.assertNotIn('--append-system-prompt', dry['command'])
            self.assertFalse((minimal / 'execution.started.json').exists())

    def test_reports_default_and_legacy_manifests_without_inventing_cache_hits(self):
        from reporting import report
        from tasks import TASKS
        with tempfile.TemporaryDirectory() as temporary:
            for conditions in (('baseline', 'minimal'), ('baseline', 'full'), ('baseline', 'minimal', 'full')):
                runs = Path(temporary) / '-'.join(conditions)
                with contextlib.redirect_stdout(io.StringIO()):
                    bench.prepare(runs, 1, 17, conditions)
                # Offline fixture, not an actual model response or measured benchmark.
                for condition in conditions:
                    directory = runs / f'dedupe-{condition}-r1'
                    (directory / 'workspace/solution.py').write_text(TASKS['dedupe']['reference'], encoding='utf-8')
                    usage = {'cache_read_input_tokens': 123, 'cache_creation_input_tokens': 0} if condition == 'baseline' else {}
                    bench.write_json(directory / 'execution.json', {'mode': 'unit_test_fixture', 'exit_code': 0, 'timed_out': False, 'seconds': 1, 'usage': usage})
                    with contextlib.redirect_stdout(io.StringIO()):
                        bench.evaluate(directory)
                # Simulate a manifest written by the old release.
                manifest = json.loads((runs / 'manifest.json').read_text(encoding='utf-8'))
                manifest.pop('conditions')
                bench.write_json(runs / 'manifest.json', manifest)
                with contextlib.redirect_stdout(io.StringIO()):
                    summary = report(runs)
                self.assertEqual(set(summary['conditions']), set(conditions))
                for condition in conditions[1:]:
                    self.assertEqual(summary['comparisons'][condition]['both_success'], 1)
                import csv
                with (runs / 'results.csv').open(encoding='utf-8') as stream:
                    rows = list(csv.DictReader(stream))
                a = next(row for row in rows if row['run_id'] == 'dedupe-baseline-r1')
                b = next(row for row in rows if row['run_id'] == f'dedupe-{conditions[1]}-r1')
                self.assertEqual(a['cache_read_input_tokens'], '123')
                self.assertEqual(b['cache_read_input_tokens'], '')
                self.assertEqual(b['cache_creation_input_tokens'], '')

    def test_installer_previews_then_installs_idempotently_and_removes_only_owned_block(self):
        script = ROOT / 'scripts/install_instructions.py'
        with tempfile.TemporaryDirectory(prefix='project 한글 & ') as temporary:
            target = Path(temporary)
            original = b'\xef\xbb\xbf# Existing rules\r\nKeep my commands.\r\n'
            (target / 'CLAUDE.md').write_bytes(original)
            (target / '.claude').mkdir()
            settings = target / '.claude/settings.json'
            settings.write_bytes(b'{"model":"unchanged"}')
            command = [sys.executable, str(script), '--target', str(target), '--cli', 'both']
            def run(*extra):
                result = subprocess.run(command + list(extra), capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            preview = run()
            self.assertFalse(preview['applied'])
            self.assertEqual((target / 'CLAUDE.md').read_bytes(), original)
            self.assertFalse((target / 'AGENTS.md').exists())
            run('--apply')
            installed = (target / 'CLAUDE.md').read_bytes()
            self.assertTrue(installed.startswith(original))
            self.assertIn((ROOT / 'minimal-kit/INSTRUCTIONS.md').read_bytes(), installed)
            run('--apply')
            self.assertEqual((target / 'CLAUDE.md').read_bytes(), installed)
            run('--remove', '--apply')
            self.assertEqual((target / 'CLAUDE.md').read_bytes(), original)
            self.assertFalse((target / 'AGENTS.md').exists())
            self.assertEqual(settings.read_bytes(), b'{"model":"unchanged"}')
            run('--remove', '--apply')

    def test_installer_refuses_conflicts_before_writing_other_destination(self):
        from scripts.install_instructions import install, START_TOKEN
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            broken = b'# User rules\n' + START_TOKEN + b'\nunfinished block'
            (target / 'AGENTS.md').write_bytes(broken)
            with self.assertRaisesRegex(ValueError, 'markers'):
                install(target, apply=True)
            self.assertFalse((target / 'CLAUDE.md').exists())
            self.assertEqual((target / 'AGENTS.md').read_bytes(), broken)

    def test_installer_updates_owned_text_and_preserves_new_user_suffix(self):
        from scripts.install_instructions import install, START, END
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            before = b'# Existing rules without newline'
            suffix = b'\r\n# Newly added user notes\r\n'
            (target / 'CLAUDE.md').write_bytes(before + START + b'old owned instructions\n' + END + suffix)
            install(target, cli='claude', apply=True)
            expected = before + START + (ROOT / 'minimal-kit/INSTRUCTIONS.md').read_bytes() + END + suffix
            self.assertEqual((target / 'CLAUDE.md').read_bytes(), expected)
            self.assertFalse((target / 'AGENTS.md').exists())
            install(target, cli='claude', apply=True, remove=True)
            self.assertEqual((target / 'CLAUDE.md').read_bytes(), before + suffix)

    def test_installer_refuses_symlink_destinations(self):
        from scripts.install_instructions import install
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            outside = target / 'user-rules.md'
            outside.write_bytes(b'Keep me')
            try:
                (target / 'CLAUDE.md').symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest('Symlink creation not available on this host')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                install(target, apply=True)
            self.assertEqual(outside.read_bytes(), b'Keep me')
            self.assertFalse((target / 'AGENTS.md').exists())

    def test_invalid_conditions_do_not_create_partial_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            for conditions in ([], ['minimal'], ['full', 'baseline'], ['baseline', 'minimal', 'minimal'], ['baseline', 'unknown']):
                runs = Path(temporary) / 'runs'
                with self.assertRaises(ValueError):
                    bench.prepare(runs, 1, 17, conditions)
                self.assertFalse(runs.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
