"""Native Windows/POSIX process, locking and Claude hook adapters (stdlib only)."""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

IS_WINDOWS = os.name == 'nt'


@contextmanager
def file_lock(path, timeout=600):
    """Lock one byte with msvcrt on Windows; flock on POSIX. Never truncate."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'r+b') as stream:
        # Windows byte-range locks may extend beyond EOF. Do not initialize a
        # sentinel before locking: another first-time caller may already own it.
        started = time.monotonic()
        acquired = False
        try:
            while not acquired:
                stream.seek(0)
                try:
                    if IS_WINDOWS:
                        import msvcrt
                        getattr(msvcrt, 'locking')(stream.fileno(), getattr(msvcrt, 'LK_NBLCK'), 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if time.monotonic() - started >= timeout:
                        raise TimeoutError(f'Lock timed out: {path}') from exc
                    time.sleep(0.02)
            yield
        finally:
            if acquired:
                stream.seek(0)
                if IS_WINDOWS:
                    import msvcrt
                    getattr(msvcrt, 'locking')(stream.fileno(), getattr(msvcrt, 'LK_UNLCK'), 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def process_options():
    if IS_WINDOWS:
        return {'creationflags': getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP')}
    return {'start_new_session': True}


def stop_process_tree(process):
    """Terminate children too; Windows uses the OS taskkill executable, not Bash."""
    if IS_WINDOWS:
        taskkill = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe')
        try:
            subprocess.run([taskkill, '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            process.kill()
    else:
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


def find_claude():
    # Honor PATH order: a later native install must not replace the active npm CLI.
    return shutil.which('claude') or (shutil.which('claude.exe') if IS_WINDOWS else None)


def claude_command(executable):
    """Resolve standard npm Windows shims without passing user arguments to CMD."""
    if not executable:
        raise ValueError('Claude Code not found on PATH')
    shim = Path(executable)
    if not IS_WINDOWS or shim.suffix.lower() not in ('.cmd', '.bat'):
        return [str(executable)]
    local_bin = shim.parent.name.lower() == '.bin'
    modules = shim.parent.parent if local_bin else shim.parent / 'node_modules'
    package = modules / '@anthropic-ai' / 'claude-code'
    try:
        manifest = json.loads((package / 'package.json').read_text(encoding='utf-8'))
        entry = manifest['bin']
        entry = entry['claude'] if isinstance(entry, dict) else entry
        if manifest.get('name') != '@anthropic-ai/claude-code' or not isinstance(entry, str):
            raise ValueError('not the official Claude Code package')
        relative = Path(entry.replace('\\', '/')).as_posix()
        target = (package / relative).resolve()
        target.relative_to(package.resolve())
        shim_text = shim.read_text(encoding='utf-8-sig').replace('\\', '/').lower()
        expected = ('../' if local_bin else 'node_modules/') + '@anthropic-ai/claude-code/' + relative.lower()
        if expected not in shim_text or '%*' not in shim_text:
            raise ValueError('not a recognized npm shim')
        if not target.is_file():
            raise ValueError('npm entry point is missing')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'Cannot resolve npm Claude shim {shim}: {exc}. Repair the npm installation or use native Claude Code; custom batch wrappers are not supported.') from exc
    if target.suffix.lower() == '.exe':
        return [str(target)]
    if target.suffix.lower() not in ('.js', '.cjs', '.mjs'):
        raise ValueError(f'Unsupported npm Claude entry point: {target}')
    adjacent_node = shim.parent / 'node.exe'
    node = str(adjacent_node) if adjacent_node.is_file() else shutil.which('node.exe')
    if not node:
        raise ValueError('Node.js (node.exe) is required for this npm Claude installation; install Node.js or repair PATH.')
    if Path(node).suffix.lower() in ('.cmd', '.bat'):
        raise ValueError('Node.js must resolve to node.exe, not a batch wrapper')
    return [str(node), str(target)]


def utf8_environment(env=None):
    result = dict(os.environ if env is None else env)
    result.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    # Ensure the current Python is also available under its native CLI name.
    result['PATH'] = str(Path(sys.executable).parent) + os.pathsep + result.get('PATH', '')
    return result


def configure_stdio():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            getattr(stream, 'reconfigure')(encoding='utf-8')


def hook_settings(kit, python_executable=None, windows=None):
    """Generate from the template so timeout/matcher changes are preserved."""
    kit = Path(kit)
    config = json.loads((kit / 'settings.json').read_text(encoding='utf-8'))
    # Keep the treatment explicit even when inherited user settings disable hooks.
    # Managed organization policy still takes precedence and is never bypassed.
    config['disableAllHooks'] = False
    windows = IS_WINDOWS if windows is None else windows
    executable = python_executable or sys.executable
    for groups in config['hooks'].values():
        for group in groups:
            for hook in group['hooks']:
                if windows:
                    hook['shell'] = 'powershell'
                    hook['command'] = ("$ErrorActionPreference = 'Stop'; "
                                       "$utf8 = [System.Text.UTF8Encoding]::new($false); "
                                       "[Console]::InputEncoding = $utf8; [Console]::OutputEncoding = $utf8; $OutputEncoding = $utf8; "
                                       "$payload = [Console]::In.ReadToEnd(); "
                                       "$payload | & $env:LOCAL_QUALITY_PYTHON (Join-Path $env:LOCAL_QUALITY_KIT 'hook.py'); exit $LASTEXITCODE")
                else:
                    import shlex
                    hook['command'] = shlex.quote(executable) + ' ' + shlex.quote(str(kit / 'hook.py'))
                    hook.pop('shell', None)
    return config


def workflow_prompt(kit):
    text = (Path(kit) / 'PROMPT.md').read_text(encoding='utf-8')
    if IS_WINDOWS:
        text = text.replace('"$LOCAL_QUALITY_PYTHON" "$LOCAL_QUALITY_KIT/compact_run.py" -- COMMAND ARGUMENTS', "& $env:LOCAL_QUALITY_PYTHON (Join-Path $env:LOCAL_QUALITY_KIT 'compact_run.py') -- COMMAND ARGUMENTS")
        text += '\nNative Windows: use PowerShell syntax, python -m unittest, UTF-8 files; do not assume Bash or WSL exists.\n'
    return text
