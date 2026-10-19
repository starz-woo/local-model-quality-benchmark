#!/usr/bin/env python3
"""Run all self-tests on native Windows, macOS or Linux; no model calls."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    temporary = root / '.test-tmp'
    temporary.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary))
    commands = [
        (root, ['test_benchmark.py', 'test_native_runtime.py']),
        (root / 'quality-kit', ['test_kit.py']),
    ]
    for cwd, tests in commands:
        result = subprocess.run([sys.executable, '-m', 'unittest', '-v'] + tests, cwd=cwd, env=env)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
