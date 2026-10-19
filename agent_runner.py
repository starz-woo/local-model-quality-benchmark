"""Explicit local Anthropic-compatible endpoint runner; no network calls on dry run."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse


def validate_endpoint(value):
    url = urlparse(value)
    host = url.hostname
    loopback = host == 'localhost'
    if host and not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
    if url.scheme not in ('http', 'https') or not loopback or url.username or url.password or url.query or url.fragment:
        raise ValueError('Use a loopback http(s) Anthropic-compatible base URL without credentials/query. This runner does not target cloud endpoints.')
    return value


def ancestor_instructions(workspace):
    files = {}
    for parent in workspace.parents:
        candidates = [parent / name for name in ('CLAUDE.md', 'CLAUDE.local.md', '.claude/CLAUDE.md', '.claude/CLAUDE.local.md')]
        rules = parent / '.claude' / 'rules'
        if rules.is_dir():
            candidates.extend(rules.rglob('*.md'))
        for path in candidates:
            if path.is_file():
                files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def execute(directory, args, run_process, write_json):
    validate_endpoint(args.base_url)
    meta = json.loads((directory / 'meta.json').read_text())
    if (directory / 'execution.json').exists() or (directory / 'execution.started.json').exists():
        raise ValueError('Run was already started. Never reuse a modified workspace; prepare a new --runs directory.')
    workspace = directory / 'workspace'
    command = [shutil.which('claude') or 'claude', '-p', (workspace / 'TASK.md').read_text(), '--model', args.model, '--output-format', 'json', '--no-session-persistence', '--settings', str(directory / 'settings.json'), '--setting-sources', '', '--strict-mcp-config', '--mcp-config', str(directory / 'mcp.json')]
    env = os.environ.copy()
    env['ANTHROPIC_BASE_URL'] = args.base_url
    env['CLAUDE_CONFIG_DIR'] = str(directory / 'claude-config')
    command += ['--permission-mode', 'acceptEdits', '--allowedTools', f'Bash(python3 -m unittest *),Bash({sys.executable} -m unittest *)']
    instruction_inputs = ancestor_instructions(workspace)
    # Each candidate has a fresh working directory; do not load personal auto-memory.
    if meta['condition'] == 'full':
        kit = directory / 'kit'
        env['LOCAL_QUALITY_KIT'] = str(kit)
        env['LOCAL_QUALITY_PYTHON'] = sys.executable
        command += ['--append-system-prompt', (kit / 'PROMPT.md').read_text()]
    if not args.execute:
        print(json.dumps({'dry_run': True, 'run_id': meta['run_id'], 'base_url': args.base_url, 'cwd': str(workspace), 'command': command, 'isolated_config_dir': env['CLAUDE_CONFIG_DIR'], 'ancestor_instructions': instruction_inputs}, ensure_ascii=False))
        return
    if instruction_inputs and not args.allow_ancestor_instructions:
        raise ValueError('Ancestor instructions detected. Use a clean ancestry or explicitly --allow-ancestor-instructions; inputs are recorded in dry run.')
    Path(env['CLAUDE_CONFIG_DIR']).mkdir(exist_ok=True)
    if not shutil.which('claude'):
        raise ValueError('claude executable not found')
    if args.timeout <= 0:
        raise ValueError('timeout must be positive')
    from integrity import inventory
    if inventory(workspace) != meta['initial_sha256']:
        raise ValueError('Workspace is not pristine (changed, missing or extra files). Prepare a new run.')
    try:
        version = subprocess.run([command[0], '--version'], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        version = 'unavailable'
    audit = {'run_id': meta['run_id'], 'model': args.model, 'model_notes': args.model_notes, 'base_url': args.base_url, 'claude_version': version, 'timeout_seconds': args.timeout, 'settings_sha256': hashlib.sha256((directory / 'settings.json').read_bytes()).hexdigest(), 'mode': 'real_agent_invocation', 'instruction_inputs': instruction_inputs, 'isolated_config_dir': env['CLAUDE_CONFIG_DIR'], 'usage': {}, 'response': ''}
    write_json(directory / 'execution.started.json', audit)
    result = run_process(command, workspace, directory / 'agent-output.json', args.timeout, env=env)
    try:
        output = json.loads((directory / 'agent-output.json').read_text())
        if not isinstance(output, dict):
            raise ValueError('Expected Claude JSON result object')
        api_error = bool(output.get('is_error')) or output.get('subtype') not in (None, 'success') or output.get('type') != 'result'
        response = output.get('result', '')
        if not isinstance(response, str):
            response = json.dumps(response, ensure_ascii=False)
        usage = output.get('usage', {})
        if not isinstance(usage, dict):
            usage = {}
    except (ValueError, OSError) as exc:
        api_error, response, usage = True, '', {}
        result['parse_error'] = str(exc)
    audit.update(result, api_error=api_error, response=response, usage=usage)
    write_json(directory / 'execution.json', audit)
    print(json.dumps({'run_id': meta['run_id'], 'exit_code': audit['exit_code'], 'timed_out': audit['timed_out'], 'api_error': api_error, 'seconds': audit['seconds']}, ensure_ascii=False))
