"""Offline checks for the user-supplied standalone experiment.

Dependencies/UI/client are mocked before import: no pip, HTTP or shell calls.
These are behavior fixtures, not a model execution or cache benchmark.
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent


def load_offline():
    exports = {
        'openai': ['OpenAI'], 'duckduckgo_search': ['DDGS'], 'rich': [],
        'rich.console': ['Console'], 'rich.live': ['Live'], 'rich.panel': ['Panel'],
        'rich.syntax': ['Syntax'], 'rich.text': ['Text'], 'rich.tree': ['Tree'],
        'rich.box': ['ROUNDED'],
    }
    modules = {}
    for name, attributes in exports.items():
        module = ModuleType(name)
        for attribute in attributes:
            setattr(module, attribute, MagicMock(name=f'{name}.{attribute}'))
        modules[name] = module
    spec = importlib.util.spec_from_file_location('standalone_agent_offline', ROOT / 'agent.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules), patch.object(subprocess, 'check_call', side_effect=AssertionError('No package installs in tests')):
        spec.loader.exec_module(module)
    # A mistakenly invoked client must not silently look like a real response.
    module.client.chat.completions.create.side_effect = AssertionError('No model calls in these tests')
    return module


class StandaloneAgentTests(unittest.TestCase):
    def test_source_compiles_without_running_bootstrap(self):
        source = (ROOT / 'agent.py').read_text(encoding='utf-8')
        compile(source, str(ROOT / 'agent.py'), 'exec')

    def test_fixed_system_message_survives_loop_and_reset(self):
        module = load_offline()
        agent = module.LocalClaudeCode('offline-fixture')
        original = agent.messages[0].copy()
        with patch.object(agent, 'stream_response', return_value='fixture final answer'), patch.object(agent, 'parse_and_execute', return_value=None):
            agent.chat_loop('fixture task')
        self.assertEqual(agent.messages[0], original)
        self.assertEqual(agent.messages[-1]['role'], 'assistant')
        agent.reset_context()
        self.assertEqual(agent.messages, [original])

    def test_loop_respects_step_cap_without_real_tools(self):
        module = load_offline()
        agent = module.LocalClaudeCode('offline-fixture')
        with patch.object(agent, 'stream_response', return_value='<read>fixture</read>') as model, patch.object(agent, 'parse_and_execute', return_value='Obs: fixture'):
            agent.chat_loop('fixture task', max_steps=2)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(agent.messages[0]['content'], module.SYSTEM_PROMPT)

    def test_real_temp_file_read_edit_and_rejection(self):
        module = load_offline()
        agent = module.LocalClaudeCode('offline-fixture')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'sample.py'
            module.console.input.return_value = 'n'
            agent.tool_edit(str(path), 'x = 1')
            self.assertFalse(path.exists())
            module.console.input.return_value = 'y'
            agent.tool_edit(str(path), 'x = 1')
            self.assertEqual(agent.tool_read(str(path)), 'x = 1\n')
            agent.tool_edit(str(path), '<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE')
            self.assertEqual(path.read_text(encoding='utf-8'), 'x = 2\n')

    def test_denied_shell_does_not_execute(self):
        module = load_offline()
        agent = module.LocalClaudeCode('offline-fixture')
        module.console.input.return_value = 'n'
        with patch.object(subprocess, 'run', side_effect=AssertionError('No shell execution')) as run:
            self.assertIn('aborted', agent.tool_bash('fixture command'))
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
