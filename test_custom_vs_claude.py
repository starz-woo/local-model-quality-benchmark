"""Offline packaging checks; never run the benchmark or its package bootstrap."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).with_name('benchmark_custom_vs_claude.py')


class SuppliedBenchmarkTests(unittest.TestCase):
    def test_source_compiles_and_edit_helper_runs_with_mocked_dependencies(self):
        compile(SOURCE.read_text(encoding='utf-8'), str(SOURCE), 'exec')
        modules = {}
        for name, attrs in {'openai': ['OpenAI'], 'rich': [], 'rich.console': ['Console'], 'rich.table': ['Table'], 'rich.panel': ['Panel'], 'rich.box': ['ROUNDED']}.items():
            module = ModuleType(name)
            for attr in attrs:
                setattr(module, attr, MagicMock())
            modules[name] = module
        spec = importlib.util.spec_from_file_location('supplied_benchmark_offline', SOURCE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules), patch.object(subprocess, 'check_call', side_effect=AssertionError('No pip')), patch.object(subprocess, 'run', side_effect=AssertionError('No CLI or generated code execution')):
            spec.loader.exec_module(module)
            module.client.chat.completions.create.side_effect = AssertionError('No model calls')
            benchmark = module.RealClaudeVsCustomBenchmark('offline-fixture')
            with tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                self.assertEqual(benchmark.apply_custom_edit(workspace, 'solution.py', 'print(1)'), 'Success: Created.')
                self.assertEqual((workspace / 'solution.py').read_text(encoding='utf-8'), 'print(1)\n')
                self.assertEqual(benchmark.apply_custom_edit(workspace, 'solution.py', '<<<<<<< SEARCH\nprint(1)\n=======\nprint(2)\n>>>>>>> REPLACE'), 'Success: Updated.')
                self.assertEqual((workspace / 'solution.py').read_text(encoding='utf-8'), 'print(2)\n\n')
                self.assertEqual(benchmark.verify_output(workspace, 'missing.py', ''), (False, 'File not created'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
