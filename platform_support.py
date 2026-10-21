"""Load the shared runtime shipped inside the independently usable quality kit."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parent / 'quality-kit' / 'runtime_support.py'
_spec = importlib.util.spec_from_file_location('_local_quality_runtime', _path)
if _spec is None or _spec.loader is None:
    raise ImportError(f'Cannot load portable runtime: {_path}')
_runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_runtime)
IS_WINDOWS = _runtime.IS_WINDOWS
process_options = _runtime.process_options
stop_process_tree = _runtime.stop_process_tree
find_claude = _runtime.find_claude
claude_command = _runtime.claude_command
utf8_environment = _runtime.utf8_environment
configure_stdio = _runtime.configure_stdio
hook_settings = _runtime.hook_settings
workflow_prompt = _runtime.workflow_prompt


def opencode_command(executable):
    """Resolve official npm opencode-ai shims without CMD argument interpolation.

    Support both older extensionless Node launchers and newer native .exe bins.
    Never execute a custom batch wrapper or trust an escaping manifest path.
    """
    import json
    import shutil
    shim = Path(executable)
    if not IS_WINDOWS or shim.suffix.lower() not in ('.cmd', '.bat'):
        return [str(executable)]
    local_bin = shim.parent.name.lower() == '.bin'
    modules = shim.parent.parent if local_bin else shim.parent / 'node_modules'
    package = modules / 'opencode-ai'
    try:
        manifest = json.loads((package / 'package.json').read_text(encoding='utf-8'))
        entry = manifest['bin']
        entry = entry['opencode'] if isinstance(entry, dict) else entry
        if manifest.get('name') != 'opencode-ai' or not isinstance(entry, str):
            raise ValueError('not the official opencode-ai package')
        relative = Path(entry.replace('\\', '/')).as_posix()
        target = (package / relative).resolve()
        target.relative_to(package.resolve())
        text = shim.read_text(encoding='utf-8-sig').replace('\\', '/').lower()
        expected = ('../' if local_bin else 'node_modules/') + 'opencode-ai/' + relative.lower()
        if expected not in text or '%*' not in text or not target.is_file():
            raise ValueError('unrecognized or incomplete npm shim')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('Cannot resolve OpenCode npm shim; use the official opencode-ai installation or native executable') from exc
    if target.suffix.lower() == '.exe':
        return [str(target)]
    if target.suffix.lower() not in ('', '.js', '.cjs', '.mjs'):
        raise ValueError('Unsupported OpenCode npm entry type')
    adjacent = shim.parent / 'node.exe'
    node = str(adjacent) if adjacent.is_file() else shutil.which('node.exe')
    if not node or Path(node).suffix.lower() != '.exe':
        raise ValueError('node.exe is required for this OpenCode npm installation')
    return [str(node), str(target)]
