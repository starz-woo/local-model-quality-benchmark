#!/usr/bin/env python3
"""Explicit command runner: compact output, keep private full logs, preserve status."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        parser.error('Expected -- COMMAND ARGUMENTS')
    fd, name = tempfile.mkstemp(prefix='local-quality-log-', suffix='.txt')
    with os.fdopen(fd, 'wb') as output:
        try:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, start_new_session=(os.name == 'posix'))
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 127
        try:
            code = process.wait(timeout=args.timeout)
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
            code = 124
    path = Path(name)
    size = path.stat().st_size
    with path.open('rb') as stream:
        if size <= 6000:
            data = stream.read()
        else:
            head = stream.read(3000)
            stream.seek(-3000, os.SEEK_END)
            data = head + b'\n... [middle omitted; inspect full log] ...\n' + stream.read(3000)
    print(f'Exit: {code}\nFull log: {path}\nLog bytes: {size}\n--- untrusted command output ---')
    print(data.decode('utf-8', errors='replace'))
    return code if code >= 0 else 128 - code


if __name__ == '__main__':
    sys.exit(main())
