#!/usr/bin/env python3
"""Preview/apply project-scoped instructions without changing CLI settings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'minimal-kit' / 'INSTRUCTIONS.md'
START_TOKEN = b'<!-- local-quality-benchmark:minimal:start -->'
END_TOKEN = b'<!-- local-quality-benchmark:minimal:end -->'
START = b'\n\n' + START_TOKEN + b'\n'
END = END_TOKEN + b'\n'


def render(original, source, remove=False):
    """Keep all user bytes outside the explicit managed block unchanged."""
    original.decode('utf-8-sig')
    starts, ends = original.count(START_TOKEN), original.count(END_TOKEN)
    block = START + source + END
    if not starts and not ends:
        return original if remove else original + block
    if starts != 1 or ends != 1 or START not in original or END not in original:
        raise ValueError('Conflicting or malformed managed markers; no files changed.')
    first = original.index(START)
    last = original.index(END) + len(END)
    if last <= first:
        raise ValueError('Reversed managed markers; no files changed.')
    return original[:first] + (b'' if remove else block) + original[last:]


def install(target, cli='both', apply=False, remove=False):
    target = Path(target).resolve()
    if not target.is_dir():
        raise ValueError('--target must be an existing project directory')
    source = SOURCE.read_bytes()
    files = {'claude': ['CLAUDE.md'], 'codex': ['AGENTS.md'], 'both': ['CLAUDE.md', 'AGENTS.md']}[cli]
    plans = []
    # Validate every destination before writing either file.
    for name in files:
        path = target / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f'Refusing symlink or non-file: {path}')
        existed = path.exists()
        before = path.read_bytes() if existed else b''
        after = render(before, source, remove)
        action = 'unchanged' if before == after else 'remove' if not after else 'update' if existed else 'create'
        plans.append((path, existed, before, after, action))
    if apply:
        for path, existed, before, after, action in plans:
            if action == 'unchanged':
                continue
            if path.is_symlink() or path.exists() != existed or (existed and path.read_bytes() != before):
                raise ValueError(f'Destination changed since preview: {path}; rerun after reviewing it.')
            if not after:
                path.unlink()
                continue
            # Same-directory replacement preserves all bytes outside our block.
            descriptor, temporary = tempfile.mkstemp(prefix='.minimal-instructions-', dir=target)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(after)
                if existed:
                    os.chmod(temporary, path.stat().st_mode)
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
    return {'applied': apply, 'operation': 'remove' if remove else 'install', 'target': str(target),
            'source_sha256': hashlib.sha256(source).hexdigest(),
            'files': [{'path': str(path), 'action': action} for path, _, _, _, action in plans],
            'note': 'Instructions only; no hooks, model calls, settings changes or cache activation. Restart the CLI to load updates.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--cli', choices=('claude', 'codex', 'both'), default='both')
    parser.add_argument('--apply', action='store_true', help='Write changes; default is preview only')
    parser.add_argument('--remove', action='store_true', help='Remove only our managed block')
    args = parser.parse_args()
    try:
        result = install(args.target, args.cli, args.apply, args.remove)
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
