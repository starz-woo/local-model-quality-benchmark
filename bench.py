#!/usr/bin/env python3
"""Paired, opt-in Claude Code local-quality benchmark. No model calls on prepare."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys

from tasks import TASKS, COMMON
from platform_support import IS_WINDOWS, process_options, stop_process_tree, hook_settings, configure_stdio, utf8_environment

ROOT = Path(__file__).resolve().parent


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(runs, repeats, seed):
    if repeats < 1:
        raise ValueError('repeats must be positive')
    if runs.exists() and any(runs.iterdir()):
        raise ValueError('Output directory is not empty; use a new --runs path. Existing work is never overwritten.')
    runs.mkdir(parents=True, exist_ok=True)
    schedule = []
    for task_id, task in TASKS.items():
        for repeat in range(1, repeats + 1):
            for condition in ('baseline', 'full'):
                run_id = f'{task_id}-{condition}-r{repeat}'
                directory = runs / run_id
                workspace = directory / 'workspace'
                (workspace / 'tests').mkdir(parents=True)
                (workspace / 'solution.py').write_text(task['starter'], encoding='utf-8', newline='\n')
                (workspace / 'TASK.md').write_text(task['request'] + (COMMON.replace('python3 -m unittest', 'python -m unittest') if IS_WINDOWS else COMMON), encoding='utf-8', newline='\n')
                (workspace / 'tests' / 'test_public.py').write_text(task['public'], encoding='utf-8', newline='\n')
                initial = {path.relative_to(workspace).as_posix(): digest(path.read_bytes()) for path in workspace.rglob('*') if path.is_file()}
                settings = {'autoMemoryEnabled': False}
                if condition == 'full':
                    shutil.copytree(ROOT / 'quality-kit', directory / 'kit', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                    config_path = directory / 'kit' / 'config.json'
                    config = json.loads(config_path.read_text(encoding='utf-8'))
                    config['test_commands'] = [[sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']]
                    write_json(config_path, config)
                    settings.update(hook_settings(directory / 'kit'))
                else:
                    settings['disableAllHooks'] = True
                write_json(directory / 'settings.json', settings)
                write_json(directory / 'mcp.json', {'mcpServers': {}})
                write_json(directory / 'meta.json', {'run_id': run_id, 'task_id': task_id, 'condition': condition, 'repeat': repeat, 'initial_sha256': initial})
                schedule.append(run_id)
    random.Random(seed).shuffle(schedule)
    write_json(runs / 'manifest.json', {'seed': seed, 'repeats': repeats, 'schedule': schedule, 'note': 'Task fixtures and metadata only. No model performance has been measured.'})
    print(json.dumps({'prepared_runs': len(schedule), 'runs': str(runs), 'model_calls': 0}, ensure_ascii=False))


def run_process(command, cwd, output_path, timeout, env=None):
    import subprocess
    import time
    start = time.monotonic()
    with output_path.open('wb') as output:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=utf8_environment(env), stdout=output, stderr=subprocess.STDOUT, **process_options())
        except OSError as exc:
            return {'exit_code': None, 'timed_out': False, 'seconds': time.monotonic() - start, 'error': str(exc)}
        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            stop_process_tree(process)
            code = process.returncode
    return {'exit_code': code, 'timed_out': timed_out, 'seconds': time.monotonic() - start}


def selected(runs, run_id=None):
    manifest = json.loads((runs / 'manifest.json').read_text(encoding='utf-8'))
    if run_id is not None and run_id not in manifest['schedule']:
        raise ValueError('Unknown run ID')
    return [runs / name for name in manifest['schedule'] if run_id is None or name == run_id]


def evaluate(directory):
    meta = json.loads((directory / 'meta.json').read_text(encoding='utf-8'))
    workspace = directory / 'workspace'
    from integrity import snapshot
    before_snapshot = snapshot(directory)
    initial = meta['initial_sha256']
    actual = before_snapshot['workspace']
    protected = [name for name in sorted(set(initial) | set(actual))
                 if (name != 'solution.py' and initial.get(name) != actual.get(name))
                 or actual.get(name) == 'SYMLINK_NOT_ALLOWED']
    execution_file = directory / 'execution.json'
    execution = json.loads(execution_file.read_text(encoding='utf-8')) if execution_file.exists() else None
    process = run_process([sys.executable, '-I', str(ROOT / 'grader.py'), meta['task_id'], str(workspace / 'solution.py')], workspace, directory / 'grader-output.json', 30)
    try:
        grade = json.loads((directory / 'grader-output.json').read_text(encoding='utf-8'))
    except (ValueError, OSError):
        grade = {'passed': False, 'tests_run': 0, 'detail': 'Grader did not return valid JSON; inspect grader-output.json.'}
    functional = process['exit_code'] == 0 and not process['timed_out'] and grade.get('passed') is True
    after_snapshot = snapshot(directory)
    changed_during_grading = before_snapshot != after_snapshot
    output = dict(meta, functional_pass=functional, protected_changes=protected, success=functional and not protected and not changed_during_grading, measured_agent_run=execution is not None, execution=execution, grader=grade, grader_process=process, snapshot=after_snapshot, changed_during_grading=changed_during_grading)
    write_json(directory / 'evaluation.json', output)
    print(json.dumps({'run_id': meta['run_id'], 'functional_pass': functional, 'protected_changes': protected, 'measured_agent_run': execution is not None}, ensure_ascii=False))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, default=ROOT / 'runs')
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--seed', type=int, default=17)
    p = sub.add_parser('evaluate')
    p.add_argument('--id')
    sub.add_parser('report')
    p = sub.add_parser('run')
    p.add_argument('--id')
    p.add_argument('--model')
    p.add_argument('--base-url')
    p.add_argument('--inherit-cli-config', action='store_true', help='Preserve existing Claude model mapping, settings and MCP connections')
    p.add_argument('--model-notes', default='not recorded; fill model/quantization/server settings for reproducibility')
    p.add_argument('--timeout', type=float, default=300)
    p.add_argument('--execute', action='store_true', help='Actually invoke Claude; otherwise dry run only')
    p.add_argument('--allow-ancestor-instructions', action='store_true', help='Explicitly accept recorded instruction contamination')
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            prepare(args.runs.resolve(), args.repeats, args.seed)
        elif args.action == 'evaluate':
            for directory in selected(args.runs.resolve(), args.id):
                evaluate(directory)
        elif args.action == 'run':
            from agent_runner import execute
            for directory in selected(args.runs.resolve(), args.id):
                execute(directory, args, run_process, write_json)
        elif args.action == 'report':
            from reporting import report
            report(args.runs.resolve())
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    configure_stdio()
    main()
