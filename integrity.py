"""Integrity snapshots; only interpreter/linter caches are excluded."""
import hashlib

IGNORED_DIRS = {'__pycache__', '.pytest_cache', '.ruff_cache'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inventory(workspace):
    result = {}
    for path in sorted(workspace.rglob('*')):
        relative = path.relative_to(workspace)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        if path.is_symlink():
            result[relative.as_posix()] = 'SYMLINK_NOT_ALLOWED'
        elif path.is_file():
            result[relative.as_posix()] = digest(path.read_bytes())
    return result


def execution_hash(directory):
    path = directory / 'execution.json'
    return digest(path.read_bytes()) if path.exists() else None


def snapshot(directory):
    return {'workspace': inventory(directory / 'workspace'), 'execution_sha256': execution_hash(directory)}


def current(directory, evaluation):
    return evaluation.get('snapshot') == snapshot(directory)
