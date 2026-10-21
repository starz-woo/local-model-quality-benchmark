#!/usr/bin/env python3
"""Launch existing Claude unchanged by default; legacy hooks require --legacy-full."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from runtime_support import find_claude, claude_command, hook_settings, workflow_prompt, utf8_environment, configure_stdio

KIT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument('--baseline', action='store_true', help='Compatibility alias for default passthrough; installed MD/settings still apply')
    profile.add_argument('--legacy-full', action='store_true', help='Explicitly add experimental legacy hooks and prompt; may increase runtime')
    parser.add_argument('--check', action='store_true', help='Check prerequisites without calling a model')
    args, extra = parser.parse_known_args()
    claude = find_claude()
    if not claude:
        parser.error('Claude Code not found on PATH')
    try:
        prefix = claude_command(claude)
    except ValueError as exc:
        parser.error(str(exc))
    if args.check:
        config = json.loads((KIT / 'config.json').read_text(encoding='utf-8'))
        print(json.dumps({'claude': claude, 'command_prefix': prefix, 'project': str(Path.cwd()), 'kit': str(KIT), 'profile': 'legacy-full' if args.legacy_full else 'passthrough', 'config': config if args.legacy_full else None}, ensure_ascii=False, indent=2))
        return 0
    env = utf8_environment()
    if not args.legacy_full:
        return subprocess.call(prefix + extra, env=env)
    env['LOCAL_QUALITY_KIT'] = str(KIT)
    env['LOCAL_QUALITY_PYTHON'] = sys.executable
    with tempfile.TemporaryDirectory(prefix='local-quality-launch-') as directory:
        settings = Path(directory) / 'settings.json'
        settings.write_text(json.dumps(hook_settings(KIT), ensure_ascii=False), encoding='utf-8', newline='\n')
        command = prefix + ['--settings', str(settings), '--append-system-prompt', workflow_prompt(KIT)]
        return subprocess.call(command + extra, env=env)


if __name__ == '__main__':
    configure_stdio()
    sys.exit(main())
