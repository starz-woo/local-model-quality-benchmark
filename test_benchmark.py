import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class BenchmarkTests(unittest.TestCase):
    def test_prepare_creates_identical_candidates_without_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / 'bench.py'), '--runs', directory, 'prepare', '--repeats', '1'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            runs = Path(directory)
            a = runs / 'dedupe-baseline-r1' / 'workspace'
            b = runs / 'dedupe-full-r1' / 'workspace'
            self.assertEqual((a / 'solution.py').read_bytes(), (b / 'solution.py').read_bytes())
            self.assertEqual((a / 'TASK.md').read_bytes(), (b / 'TASK.md').read_bytes())
            self.assertFalse((a / 'grader.py').exists())
            self.assertFalse((a / 'reference.py').exists())
            manifest = json.loads((runs / 'manifest.json').read_text())
            self.assertTrue(manifest['schedule'])


    def test_grader_rejects_starters_and_accepts_references(self):
        from tasks import TASKS
        with tempfile.TemporaryDirectory() as directory:
            for task_id, task in TASKS.items():
                for kind in ('starter', 'reference'):
                    file = Path(directory) / (task_id + '-' + kind + '.py')
                    file.write_text(task[kind], encoding='utf-8')
                    result = subprocess.run([sys.executable, '-I', str(ROOT / 'grader.py'), task_id, str(file)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    data = json.loads(result.stdout)
                    self.assertEqual(data['passed'], kind == 'reference', (task_id, kind, data))
                    self.assertGreater(data['tests_run'], 0)


    def test_evaluate_marks_protected_test_changes(self):
        from tasks import TASKS
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(ROOT / 'bench.py'), '--runs', directory]
            subprocess.run(command + ['prepare', '--repeats', '1'], check=True, capture_output=True)
            run = Path(directory) / 'dedupe-baseline-r1'
            (run / 'workspace' / 'solution.py').write_text(TASKS['dedupe']['reference'])
            result = subprocess.run(command + ['evaluate', '--id', run.name], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            grade = json.loads((run / 'evaluation.json').read_text())
            self.assertTrue(grade['functional_pass'])
            self.assertTrue(grade['success'])
            self.assertFalse(grade['measured_agent_run'])
            (run / 'workspace' / 'tests' / 'test_public.py').write_text('# weakened')
            subprocess.run(command + ['evaluate', '--id', run.name], check=True, capture_output=True)
            grade = json.loads((run / 'evaluation.json').read_text())
            self.assertTrue(grade['functional_pass'])
            self.assertFalse(grade['success'])
            self.assertIn('tests/test_public.py', grade['protected_changes'])


    def test_model_run_is_explicit_and_reports_include_pending_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(ROOT / 'bench.py'), '--runs', directory]
            subprocess.run(command + ['prepare', '--repeats', '1'], check=True, capture_output=True)
            # Report without running Claude must not invent a success rate.
            result = subprocess.run(command + ['report'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((Path(directory) / 'summary.json').read_text())
            for condition in ('baseline', 'full'):
                self.assertEqual(summary['conditions'][condition]['attempted'], 0)
                self.assertIsNone(summary['conditions'][condition]['success_rate'])
            self.assertEqual(summary['paired']['complete_pairs'], 0)
            self.assertTrue((Path(directory) / 'blind-review' / 'rubric.md').exists())
            self.assertFalse((Path(directory) / 'blind-review' / 'review-key.json').exists())


    def test_run_requires_explicit_execute_and_local_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(ROOT / 'bench.py'), '--runs', directory]
            subprocess.run(command + ['prepare', '--repeats', '1'], check=True, capture_output=True)
            args = ['run', '--id', 'dedupe-baseline-r1', '--model', 'local-test', '--base-url', 'http://127.0.0.1:9999']
            result = subprocess.run(command + args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('dry_run', result.stdout)
            dry = json.loads(result.stdout)
            self.assertIn('--permission-mode', dry['command'])
            self.assertIn('acceptEdits', dry['command'])
            self.assertIn('--allowedTools', dry['command'])
            self.assertTrue(dry['isolated_config_dir'].endswith('/claude-config'))
            self.assertFalse((Path(directory) / 'dedupe-baseline-r1' / 'execution.json').exists())
            result = subprocess.run(command + ['run', '--model', 'local-test', '--base-url', 'https://api.anthropic.com'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('loopback', result.stderr)


    def test_skipped_candidate_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / 'skip.py'
            candidate.write_text('import unittest\ndef stable_unique(items):\n    raise unittest.SkipTest("not implemented")\n')
            result = subprocess.run([sys.executable, '-I', str(ROOT / 'grader.py'), 'dedupe', str(candidate)], capture_output=True, text=True, check=True)
            grade = json.loads(result.stdout)
            self.assertFalse(grade['passed'])
            self.assertGreater(grade['skipped'], 0)


    def test_stale_evaluation_is_not_reused(self):
        from tasks import TASKS
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(ROOT / 'bench.py'), '--runs', directory]
            subprocess.run(command + ['prepare', '--repeats', '1'], check=True, capture_output=True)
            run = Path(directory) / 'dedupe-baseline-r1'
            candidate = run / 'workspace' / 'solution.py'
            candidate.write_text(TASKS['dedupe']['reference'])
            # Unit-test metadata fixture, not a real or claimed model invocation.
            execution = run / 'execution.json'
            execution.write_text(json.dumps({'exit_code': 0, 'seconds': 1, 'mode': 'unit_test_fixture'}))
            subprocess.run(command + ['evaluate', '--id', run.name], check=True, capture_output=True)
            subprocess.run(command + ['report'], check=True, capture_output=True)
            summary = json.loads((Path(directory) / 'summary.json').read_text())
            self.assertEqual(summary['conditions']['baseline']['successes'], 1)
            candidate.write_text(TASKS['dedupe']['starter'])
            subprocess.run(command + ['report'], check=True, capture_output=True)
            summary = json.loads((Path(directory) / 'summary.json').read_text())
            self.assertEqual(summary['conditions']['baseline']['pending_evaluations'], 1)
            subprocess.run(command + ['evaluate', '--id', run.name], check=True, capture_output=True)
            execution.write_text(json.dumps({'exit_code': 0, 'seconds': 2, 'mode': 'unit_test_fixture'}))
            subprocess.run(command + ['report'], check=True, capture_output=True)
            summary = json.loads((Path(directory) / 'summary.json').read_text())
            self.assertEqual(summary['conditions']['baseline']['pending_evaluations'], 1)


    def test_new_workspace_files_are_out_of_scope(self):
        from tasks import TASKS
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(ROOT / 'bench.py'), '--runs', directory]
            subprocess.run(command + ['prepare', '--repeats', '1'], check=True, capture_output=True)
            run = Path(directory) / 'dedupe-baseline-r1'
            (run / 'workspace' / 'solution.py').write_text(TASKS['dedupe']['reference'])
            (run / 'workspace' / 'extra.py').write_text('x = 1')
            subprocess.run(command + ['evaluate', '--id', run.name], check=True, capture_output=True)
            grade = json.loads((run / 'evaluation.json').read_text())
            self.assertFalse(grade['success'])
            self.assertIn('extra.py', grade['protected_changes'])


    def test_review_template_adds_new_ids_without_erasing_scores(self):
        import csv
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(ROOT / 'bench.py'), '--runs', directory]
            subprocess.run(command + ['prepare', '--repeats', '1'], check=True, capture_output=True)
            subprocess.run(command + ['report'], check=True, capture_output=True)
            root = Path(directory)
            fixture = {'exit_code': 0, 'seconds': 1, 'mode': 'unit_test_fixture'}
            (root / 'dedupe-baseline-r1' / 'execution.json').write_text(json.dumps(fixture))
            subprocess.run(command + ['report'], check=True, capture_output=True)
            score_path = root / 'blind-review' / 'scores.template.csv'
            with score_path.open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            rows[0]['requirements_0_2'] = '2'
            with score_path.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            (root / 'dedupe-full-r1' / 'execution.json').write_text(json.dumps(fixture))
            subprocess.run(command + ['report'], check=True, capture_output=True)
            with score_path.open() as stream:
                added = list(csv.DictReader(stream))
            self.assertEqual(len(added), 2)
            self.assertEqual(next(row for row in added if row['blind_id'] == rows[0]['blind_id'])['requirements_0_2'], '2')


if __name__ == '__main__':
    unittest.main(verbosity=2)
