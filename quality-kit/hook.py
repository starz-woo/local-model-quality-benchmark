#!/usr/bin/env python3
"""Trusted local hooks. No shell=True, package installation or model calls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

KIT = Path(__file__).resolve().parent


def compact(text, limit=6000):
    if len(text) <= limit:
        return text
    half = (limit - 120) // 2
    return text[:half] + '\n... [middle omitted; inspect original output if needed] ...\n' + text[-half:]


def run_command(argv, root, timeout):
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        return False, 'Invalid command: configure a nonempty JSON array of strings.'
    # Output goes to a file rather than an unbounded in-memory pipe.
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(argv, cwd=root, stdout=output, stderr=subprocess.STDOUT, start_new_session=(os.name == 'posix'))
        except OSError as exc:
            return False, str(exc)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'posix':
                import signal
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait()
            return False, f'Command timed out after {timeout}s: {argv!r}'
        size = output.tell()
        output.seek(0)
        head = output.read(3000)
        if size > 6000:
            output.seek(-3000, os.SEEK_END)
            data = head + b'\n... [middle omitted] ...\n' + output.read(3000)
        else:
            output.seek(0)
            data = output.read()
        return code == 0, f'exit={code}; command={argv!r}\n' + data.decode('utf-8', errors='replace')


def state_path(root, event):
    key = hashlib.sha256((str(root) + '\0' + str(event.get('session_id', 'unknown'))).encode()).hexdigest()
    directory = Path(tempfile.gettempdir()) / 'local-quality-kit'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / (key + '.json')


def save(path, state):
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def emit_context(message):
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': message}}, ensure_ascii=False))


def handle(event):
    # macOS/Linux: serialize hooks for a project/session so parallel tool calls
    # cannot overwrite counters or race the Stop gate.
    import fcntl
    root = Path(os.environ.get('CLAUDE_PROJECT_DIR') or event.get('cwd') or os.getcwd()).resolve()
    lock = state_path(root, event).with_suffix('.lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        return handle_locked(event)


def handle_locked(event):
    config = json.loads((KIT / 'config.json').read_text())
    root = Path(os.environ.get('CLAUDE_PROJECT_DIR') or event.get('cwd') or os.getcwd()).resolve()
    path = state_path(root, event)
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        state = {'calls': 0, 'dirty': False, 'failures': 0}
    name = event.get('hook_event_name')
    if name == 'UserPromptSubmit':
        # Preserve unverified changes across prompts; only reset exploration budget.
        state['calls'] = 0
        state['failures'] = 0
        save(path, state)
        return 0
    if name == 'PostToolUse':
        state['calls'] += 1
        tool = event.get('tool_name', '')
        messages = []
        if state['calls'] == config['exploration_reminder_after']:
            messages.append('Exploration budget reached: stop redundant searches; implement and verify if evidence is sufficient. Otherwise state the missing evidence. Tools remain available; do not invent results.')
        if tool in ('Edit', 'Write', 'MultiEdit', 'Bash', 'PowerShell'):
            # Conservatively treat commands as potentially modifying project files.
            state['dirty'] = True
        if tool in ('Edit', 'Write', 'MultiEdit'):
            raw = event.get('tool_input', {}).get('file_path')
            if raw:
                file = Path(raw)
                if not file.is_absolute():
                    file = root / file
                file = file.resolve()
                if not file.is_relative_to(root):
                    messages.append('Edited path is outside project: this kit did not inspect it.')
                elif not file.is_file():
                    messages.append('Edited file is missing: do not report a successful write.')
                else:
                    content = file.read_bytes()
                    if tool == 'Write' and isinstance(event.get('tool_input', {}).get('content'), str):
                        expected = event['tool_input']['content'].encode('utf-8')
                        if content != expected:
                            messages.append('WRITE VERIFICATION FAILED: saved bytes differ from requested UTF-8 content; inspect file before continuing.')
                    commands = []
                    try:
                        if file.suffix == '.py':
                            compile(content, str(file), 'exec')
                        elif file.suffix == '.json':
                            json.loads(content)
                        elif file.suffix == '.sh':
                            commands.append(['bash', '-n', str(file)])
                    except (SyntaxError, ValueError, UnicodeError) as exc:
                        messages.append(f'Syntax check FAILED: {exc}')
                    for command in config.get('verify_by_suffix', {}).get(file.suffix, []):
                        commands.append([arg.replace('{file}', str(file)) for arg in command])
                    for command in commands:
                        ok, output = run_command(command, root, config['verify_timeout_seconds'])
                        if not ok:
                            messages.append('Verification FAILED; fix without weakening tests:\n' + compact(output))
        save(path, state)
        if messages:
            emit_context('\n\n'.join(messages))
        return 0
    if name == 'Stop' and state['dirty']:
        commands = config.get('test_commands', [])
        if not commands:
            print(json.dumps({'systemMessage': 'Local quality kit: no test_commands configured. Final test gate NOT RUN; do not interpret this as a pass.'}))
            return 0
        failures = []
        for command in commands:
            ok, output = run_command(command, root, config['test_timeout_seconds'])
            if not ok:
                failures.append(output)
        if not failures:
            state['dirty'] = False
            state['failures'] = 0
            save(path, state)
            return 0
        state['failures'] += 1
        save(path, state)
        if state['failures'] <= config['max_blocked_stops']:
            reason = 'Tests FAILED. Correct the failures; do not delete or weaken tests.\n' + compact('\n'.join(failures))
            print(json.dumps({'decision': 'block', 'reason': reason}, ensure_ascii=False))
        else:
            # Never report an exhausted gate as a successful test run.
            print(json.dumps({'systemMessage': 'TEST GATE FAILED: retry limit reached; stopping is allowed but tests did NOT pass.\n' + compact('\n'.join(failures))}, ensure_ascii=False))
        return 0
    return 0


if __name__ == '__main__':
    try:
        sys.exit(handle(json.load(sys.stdin)))
    except Exception as exc:
        print('Local quality hook ERROR (not a verification pass): ' + str(exc), file=sys.stderr)
        sys.exit(1)
