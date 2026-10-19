#!/usr/bin/env python3
"""Launch Claude with opt-in project-local quality guidance and hooks."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

KIT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', action='store_true', help='Do not add this kit; existing Claude settings still apply')
    parser.add_argument('--check', action='store_true', help='Check prerequisites without calling a model')
    args, extra = parser.parse_known_args()
    claude = shutil.which('claude')
    if not claude:
        parser.error('claude executable not found')
    if args.check:
        config = json.loads((KIT / 'config.json').read_text())
        print(json.dumps({'claude': claude, 'project': str(Path.cwd()), 'kit': str(KIT), 'config': config}, ensure_ascii=False, indent=2))
        return
    env = os.environ.copy()
    env['LOCAL_QUALITY_KIT'] = str(KIT)
    env['LOCAL_QUALITY_PYTHON'] = sys.executable
    command = [claude]
    if not args.baseline:
        command += ['--settings', str(KIT / 'settings.json'), '--append-system-prompt', (KIT / 'PROMPT.md').read_text()]
    os.execvpe(claude, command + extra, env)


if __name__ == '__main__':
    main()
