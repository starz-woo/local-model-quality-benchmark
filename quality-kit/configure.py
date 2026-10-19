#!/usr/bin/env python3
"""Configure this kit, never edit the project's existing Claude settings."""
import argparse
import json
from pathlib import Path
from runtime_support import configure_stdio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', nargs=argparse.REMAINDER, required=True, help='One trusted test command and its arguments; use non-watch mode')
    args = parser.parse_args()
    command = args.test
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        parser.error('Expected a test command')
    path = Path(__file__).resolve().with_name('config.json')
    original = path.read_bytes()
    config = json.loads(original)
    config['test_commands'] = [command]
    backup = path.with_suffix('.json.before-test-setup')
    if not backup.exists():
        backup.write_bytes(original)
    data = (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode()
    path.write_bytes(data)
    if path.read_bytes() != data:
        raise RuntimeError('Config readback mismatch')
    print('Configured test command (not executed): ' + repr(command))


if __name__ == '__main__':
    configure_stdio()
    main()
