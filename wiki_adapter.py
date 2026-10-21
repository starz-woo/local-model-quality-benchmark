"""Headless adapter for setup_agent.py's actual generated Wiki AgentEngine.

The original generator is preserved byte-for-byte. Only literal STRUCTURE data
is read; importing this adapter neither imports nor executes supplied code.
"""
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def generate(destination):
    tree = ast.parse((ROOT / 'setup_agent.py').read_text(encoding='utf-8'))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'STRUCTURE' for t in node.targets))
    structure = ast.literal_eval(assignment.value)
    # Three startup repairs only: quoting, decorator API, tool registration imports.
    engine = structure['agent']['engine.py']
    lines = engine.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if "if m := re.search(r'<edit" in line:
            lines[index] = '        if m := re.search(r"""<edit.*?file=[\"\']([^\"\']+)[\"\'].*?>(.*?)</edit>""", text, re.DOTALL):\n'
    structure['agent']['engine.py'] = ''.join(lines).replace(
        'from tools.base import tool_registry\n',
        'from tools.base import tool_registry\nfrom tools import file_tools, search_tools, sys_tools\n')
    structure['tools']['base.py'] = structure['tools']['base.py'].replace(
        '    def register(self, name: str, func):\n        self.registry[name] = func',
        '    def register(self, name: str, func=None):\n'
        '        def decorator(handler):\n'
        '            self.registry[name] = handler\n'
        '            return handler\n'
        '        return decorator(func) if func is not None else decorator')
    destination = Path(destination)
    for base, contents in structure.items():
        entries = contents.items() if isinstance(contents, dict) else [(None, contents)]
        for filename, code in entries:
            target = destination / base / filename if filename else destination / base
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding='utf-8')


def run(runtime, prompt, model, base_url, api_key, max_steps):
    """Called only in the explicitly authorized worker subprocess."""
    generate(runtime)
    sys.path.insert(0, str(Path(runtime).resolve()))
    from agent.engine import AgentEngine
    from ui.display import DisplayManager, console
    from openai import OpenAI
    # Keep the original engine, prompt, XML parsing, edit and tool implementations.
    # Only transport credentials and UI approval are adapted for headless use.
    DisplayManager.prompt_user_confirmation = staticmethod(lambda *args: True)
    console.input = lambda *args, **kwargs: ''  # no fallback markdown-save prompt
    engine = AgentEngine(model=model)
    engine.llm.client = OpenAI(base_url=base_url, api_key=api_key,
                               timeout=60, max_retries=0)
    engine.run_turn(prompt, max_steps=max_steps)


if __name__ == '__main__':
    import contextlib
    import json
    import os
    # Never persist streamed model output, tool output or exception text: any can
    # contain credentials. The parent records only status/exit code and timings.
    try:
        job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        with open(os.devnull, 'w', encoding='utf-8') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            run(job['runtime'], job['prompt'], job['model'], job['base_url'],
                os.environ['WIKI_BENCH_KEY'], job['max_steps'])
    except Exception:
        sys.exit(1)
