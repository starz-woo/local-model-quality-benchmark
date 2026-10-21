#!/usr/bin/env python3
"""Small native Windows runner: real generated Wiki agent versus real OpenCode.

Default is a read-only, offline preflight. Only --execute authorizes model/tool IO.
"""
import argparse
import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from platform_support import process_options, stop_process_tree, utf8_environment, configure_stdio, opencode_command
from tasks import TASKS

ROOT = Path(__file__).resolve().parent
OPENCODE_VERSION = '1.2.27'  # Deliberately pin the documented v1 config/CLI contract.


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true', help='authorize paid model calls and auto-approved native tools (NOT a sandbox)')
    p.add_argument('--model', default=os.environ.get('WIKI_BENCH_MODEL'), help='exact GLM/provider API model ID, no aliases inferred')
    p.add_argument('--base-url', default=os.environ.get('WIKI_BENCH_BASE_URL'), help='OpenAI-compatible chat-completions base URL')
    p.add_argument('--key-env', default='GLM_API_KEY', help='name of environment variable containing API key')
    p.add_argument('--opencode', default='opencode', help='installed executable or npm .cmd path')
    p.add_argument('--output', default='wiki-results', help='NEW directory; existing directories are never overwritten')
    p.add_argument('--tasks', nargs='+', choices=TASKS, default=['dedupe', 'pagination', 'money'])
    p.add_argument('--repeats', type=int, default=2, help='even repeat count for AB/BA counterbalancing')
    p.add_argument('--timeout', type=float, default=180, help='same hard wall-time seconds per agent/task')
    p.add_argument('--max-steps', type=int, default=10, help='Wiki model turns and OpenCode build agent steps')
    return p


def config(model, base_url, steps):
    selected = 'benchmark/' + model
    return {'$schema': 'https://opencode.ai/config.json',
            'model': selected, 'small_model': selected, 'default_agent': 'build',
            'autoupdate': False, 'share': 'disabled', 'plugin': [], 'mcp': {},
            'instructions': [], 'lsp': False, 'formatter': False,
            'permission': {'*': 'allow'}, 'agent': {'build': {'steps': steps}},
            'enabled_providers': ['benchmark'],
            'provider': {'benchmark': {'npm': '@ai-sdk/openai-compatible',
                'name': 'Benchmark supplied endpoint',
                'options': {'baseURL': base_url, 'apiKey': '{env:WIKI_BENCH_KEY}', 'timeout': 60000},
                'models': {model: {'name': model}}}}}


def environment(home, key):
    env = {k: v for k, v in utf8_environment().items()
           if not k.startswith('OPENCODE_') and k not in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY')}
    # Config merges, so OPENCODE_CONFIG alone is NOT isolation. Redirect user
    # config/data roots as well; do not touch the user's actual config or auth.
    for variable, subdir in {'HOME': 'home', 'USERPROFILE': 'home',
            'XDG_CONFIG_HOME': 'config', 'XDG_DATA_HOME': 'data',
            'XDG_CACHE_HOME': 'cache', 'XDG_STATE_HOME': 'state',
            'APPDATA': 'appdata', 'LOCALAPPDATA': 'localappdata',
            'OPENCODE_CONFIG_DIR': 'opencode'}.items():
        path = home / subdir
        path.mkdir(parents=True, exist_ok=True)
        env[variable] = str(path)
    env.update(WIKI_BENCH_KEY=key, OPENCODE_DISABLE_AUTOUPDATE='true',
               OPENCODE_DISABLE_DEFAULT_PLUGINS='true', OPENCODE_DISABLE_LSP_DOWNLOAD='true',
               OPENCODE_DISABLE_CLAUDE_CODE='true', OPENCODE_DISABLE_MODELS_FETCH='true',
               OPENCODE_AUTO_SHARE='false')
    return env


def process(command, cwd, env, timeout):
    """Bound the whole subprocess tree, not just a streaming HTTP request."""
    try:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, encoding='utf-8', errors='replace', **process_options())
    except OSError:
        return 'launch_error', None, ''
    try:
        output, _ = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_process_tree(child)
        child.communicate(timeout=10)
        return 'timeout', child.returncode, ''
    except BaseException:
        stop_process_tree(child)
        raise
    return ('ok' if child.returncode == 0 else 'error'), child.returncode, output


def opencode_success(output):
    """A zero exit without a completed JSON step is not a successful run."""
    events = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(value)
        except ValueError:
            continue
    return any(e.get('type') == 'step_finish' for e in events) and not any(e.get('type') == 'error' for e in events)


def grade(task_id, workspace):
    # Hidden grader never enters a candidate workspace; snapshot candidate only
    # after its process exits. Candidate Python is executed, NOT sandboxed.
    try:
        with tempfile.TemporaryDirectory(prefix='wiki-grade-') as temporary:
            target = Path(temporary) / 'solution.py'
            shutil.copyfile(workspace / 'solution.py', target)
            status, _, output = process([sys.executable, '-I', str(ROOT / 'grader.py'), task_id, str(target)],
                                         temporary, utf8_environment(), 20)
            result = json.loads(output) if status == 'ok' else {}
            return result.get('passed') is True and result.get('tests_run', 0) > 0
    except (OSError, ValueError):
        return False


def report(output, rows):
    with (output / 'results.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ['# Wiki vs OpenCode (real agents)', '',
             'Tokens: unknown (not instrumented consistently). No cost/token comparison.', '',
             '| Task | Repeat | Agent | Status | Passed | Wall seconds |',
             '|---|---:|---|---|---|---:|']
    lines.extend(f"| {r['task']} | {r['repeat']} | {r['agent']} | {r['status']} | {r['passed']} | {r['wall_seconds']:.3f} |" for r in rows)
    for agent in ('wiki', 'opencode'):
        group = [r for r in rows if r['agent'] == agent]
        lines.append(f"\n{agent}: {sum(r['passed'] for r in group)}/{len(group)} passed; "
                     f"total agent wall time {sum(r['wall_seconds'] for r in group):.3f}s (ALL attempts, including failures/timeouts).")
    lines += ['', 'See protocol.json for requested settings. Not exact model/thinking/permission parity.',
              'No sandbox; use a disposable Windows account/VM without valuable credentials.']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def execute(args, opencode, key):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    protocol = {'model': args.model, 'base_url': args.base_url, 'timeout': args.timeout,
                'max_steps': args.max_steps, 'repeats': args.repeats, 'tasks': args.tasks,
                'opencode_version_contract': OPENCODE_VERSION,
                'permissions': 'Wiki edit auto-approved; original native shell unrestricted; OpenCode all allow',
                'wiki_generation': 'original setup_agent.py literal STRUCTURE + three startup repairs',
                'thinking': 'Wiki original extra_body high/clear_thinking/cache_prompt; OpenCode provider defaults',
                'tokens': 'unknown', 'sandbox': False}
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    rows = []
    for task_id in args.tasks:
        task = TASKS[task_id]
        for repeat in range(args.repeats):
            for agent in (('wiki', 'opencode') if repeat % 2 == 0 else ('opencode', 'wiki')):
                run = output / f'{task_id}-{repeat + 1}-{agent}'
                workspace = run / 'workspace'
                workspace.mkdir(parents=True)
                wiki = workspace / '.agent_wiki'
                wiki.mkdir()
                (wiki / 'index.md').write_text('# Agent Local Wiki\n\nNo prior notes.\n', encoding='utf-8')
                (workspace / 'solution.py').write_text(task['starter'], encoding='utf-8')
                public = workspace / 'public_test.py'
                public.write_text(task['public'], encoding='utf-8')
                original_public = public.read_bytes()
                prompt = task['request'] + '\nModify only solution.py (local .agent_wiki/*.md notes allowed). Do not change public_test.py. Use only Python standard library. Run public tests: python -m unittest public_test -v. This is native Windows when on Windows: <bash> uses cmd.exe, not WSL. No interactive approval is possible. Report actual verification and finish.'
                env = environment(run / 'state', key)
                if agent == 'wiki':
                    job = run / 'job.json'
                    job.write_text(json.dumps({'runtime': str(run / 'generated'), 'prompt': prompt,
                        'model': args.model, 'base_url': args.base_url, 'max_steps': args.max_steps}), encoding='utf-8')
                    command = [sys.executable, str(ROOT / 'wiki_adapter.py'), str(job)]
                else:
                    env['OPENCODE_CONFIG_CONTENT'] = json.dumps(config(args.model, args.base_url, args.max_steps))
                    command = opencode + ['run', '--format', 'json', '--model', 'benchmark/' + args.model, '--agent', 'build', prompt]
                started = time.monotonic()
                status, code, raw = process(command, workspace, env, args.timeout)
                elapsed = time.monotonic() - started
                if agent == 'opencode' and status == 'ok' and not opencode_success(raw):
                    status = 'protocol_error'
                try:
                    intact = public.read_bytes() == original_public and not public.is_symlink()
                    extras = [p for p in workspace.rglob('*') if p.is_file() and p.name != 'solution.py'
                              and p != public and '__pycache__' not in p.parts
                              and not (p.parent == workspace / '.agent_wiki' and p.suffix == '.md')]
                    if not intact or extras or (workspace / 'solution.py').is_symlink():
                        status = 'integrity_error'
                except OSError:
                    status = 'integrity_error'
                passed = grade(task_id, workspace) if status == 'ok' else False
                rows.append({'task': task_id, 'repeat': repeat + 1, 'agent': agent,
                             'status': status, 'exit_code': code, 'passed': passed,
                             'wall_seconds': elapsed, 'tokens': 'unknown'})
                report(output, rows)  # preserve every finished attempt, even before later failures
                print(f'{task_id}/{repeat + 1}/{agent}: {status}; passed={passed}; {elapsed:.2f}s')
    return rows


def main(argv=None):
    args = parser().parse_args(argv)
    if args.repeats < 2 or args.repeats % 2 or args.max_steps < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser().error('require even --repeats >= 2, --max-steps >= 1, finite --timeout > 0')
    if len(set(args.tasks)) != len(args.tasks):
        parser().error('duplicate tasks are not allowed')
    executable = shutil.which(args.opencode)
    dependencies = [name for name in ('openai', 'rich', 'duckduckgo_search') if importlib.util.find_spec(name) is None]
    print('Offline preflight: no model calls, no package installs, no generated agent imports.')
    print('OpenCode found: ' + str(bool(executable)) + '; required CLI contract: ' + OPENCODE_VERSION)
    print('Missing Python packages: ' + (', '.join(dependencies) or 'none'))
    print(f'Plan: {len(args.tasks)} tasks x {args.repeats} repeats x 2 real agents; {args.timeout:g}s hard budget each.')
    if not args.execute:
        print('Dry run only. Supply --model EXACT_ID --base-url URL --execute to run.')
        return 0
    if not args.model or any(c in args.model for c in '{}#\r\n'):
        parser().error('--model exact ID required; config interpolation/control characters are not supported')
    url = urlsplit(args.base_url or '')
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment or '{' in args.base_url:
        parser().error('--base-url must be http(s) without embedded credentials, query, fragment or interpolation')
    if not os.environ.get(args.key_env):
        parser().error('--key-env variable is missing or empty')
    if dependencies or not executable:
        parser().error('install the listed Python dependencies and OpenCode yourself first; nothing is auto-installed')
    if Path(args.output).exists():
        parser().error('--output already exists; choose a new directory')
    try:
        command = opencode_command(executable)
    except ValueError as exc:
        parser().error(str(exc))
    status, _, version = process(command + ['--version'], ROOT, utf8_environment(), 15)
    if status != 'ok' or version.strip() != OPENCODE_VERSION:
        parser().error('OpenCode version must be ' + OPENCODE_VERSION + '; v2 schema differs. No model calls made.')
    rows = execute(args, command, os.environ[args.key_env])
    print('Reports: ' + str(Path(args.output).resolve()))
    return 0 if all(r['passed'] for r in rows) else 1


if __name__ == '__main__':
    configure_stdio()
    sys.exit(main())
