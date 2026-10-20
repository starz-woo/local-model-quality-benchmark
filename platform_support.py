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
