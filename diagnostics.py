"""Opt-in stream observability. Raw tool arguments/results never reach the console."""
import json
import queue
import re
import subprocess
import sys
import threading
import time

from platform_support import process_options, stop_process_tree, utf8_environment


def run_stream_process(command, cwd, output_path, timeout, env=None):
    start = time.monotonic()
    events_path = output_path.with_suffix('.events.jsonl')
    errors_path = output_path.with_suffix('.stderr.log')
    state = {'last': 'waiting for first event', 'final': None, 'tools': {}, 'approval_errors': 0}

    def progress(label):
        state['last'] = label
        print(f'[progress {time.monotonic() - start:.0f}s] {label}', file=sys.stderr, flush=True)

    def consume(line):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            return
        if not isinstance(event, dict):
            return
        kind = event.get('type')
        if kind == 'result':
            state['final'] = event
            progress('final result received')
        elif kind == 'system':
            # Do not echo server-controlled strings or sensitive metadata.
            progress('system event received')
        elif kind in ('assistant', 'user'):
            message = event.get('message')
            content = message.get('content', []) if isinstance(message, dict) else []
            if not isinstance(content, list):
                return
            found_tool = False
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'tool_use':
                    raw_name = block.get('name', '')
                    name = raw_name if isinstance(raw_name, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', raw_name) else 'other-tool'
                    tool_id = block.get('id')
                    if isinstance(tool_id, str):
                        state['tools'][tool_id] = name
                    progress(f'tool request: {name}')
                    found_tool = True
                elif block.get('type') == 'tool_result':
                    tool_id = block.get('tool_use_id')
                    name = state['tools'].get(tool_id, 'unknown-tool') if isinstance(tool_id, str) else 'unknown-tool'
                    outcome = 'ERROR' if block.get('is_error') else 'returned'
                    payload = block.get('content', '')
                    if isinstance(payload, list):
                        payload = ' '.join(item.get('text', '') for item in payload if isinstance(item, dict) and isinstance(item.get('text'), str))
                    if block.get('is_error') and isinstance(payload, str) and re.search(r'requires approval|approval required', payload, re.IGNORECASE):
                        state['approval_errors'] += 1
                        outcome += ' APPROVAL_REQUIRED'
                    progress(f'tool result: {name} {outcome}')
                    found_tool = True
            if kind == 'assistant' and not found_tool:
                progress('model response received')

    output_path.write_text('', encoding='utf-8')
    timed_out = False
    with events_path.open('wb') as raw, errors_path.open('wb') as errors:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=utf8_environment(env), stdout=subprocess.PIPE, stderr=errors, **process_options())
        except OSError as exc:
            return {'exit_code': None, 'timed_out': False, 'seconds': time.monotonic() - start, 'error': str(exc), 'final_result_received': False, 'last_progress': state['last'], 'approval_error_count': state['approval_errors']}
        assert process.stdout is not None
        stdout_pipe = process.stdout
        lines = queue.Queue()

        def read_stdout():
            try:
                for line in iter(stdout_pipe.readline, b''):
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()
        progress('waiting for first event')
        next_notice = start + 15
        eof = False
        try:
            while True:
                now = time.monotonic()
                if now - start >= timeout:
                    timed_out = True
                    print(f'[progress] TIMEOUT; last stage: {state["last"]}', file=sys.stderr, flush=True)
                    stop_process_tree(process)
                    break
                if eof and process.poll() is not None:
                    break
                try:
                    line = lines.get(timeout=min(0.2, max(0.001, timeout - (now - start))))
                except queue.Empty:
                    line = b''
                if line is None:
                    eof = True
                elif line:
                    raw.write(line)
                    raw.flush()
                    consume(line)
                if time.monotonic() >= next_notice:
                    print(f'[progress {time.monotonic() - start:.0f}s] waiting; last stage: {state["last"]}', file=sys.stderr, flush=True)
                    next_notice = time.monotonic() + 15
        except BaseException:
            stop_process_tree(process)
            raise
        finally:
            reader.join(timeout=2)
            while True:
                try:
                    line = lines.get_nowait()
                except queue.Empty:
                    break
                if line:
                    raw.write(line)
                    consume(line)
            if not reader.is_alive():
                stdout_pipe.close()
        code = process.wait(timeout=10)
    final = state['final']
    if final is not None:
        output_path.write_text(json.dumps(final, ensure_ascii=False), encoding='utf-8')
    return {'exit_code': code, 'timed_out': timed_out, 'seconds': time.monotonic() - start, 'final_result_received': final is not None, 'last_progress': state['last'], 'approval_error_count': state['approval_errors']}
