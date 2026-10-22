"""Read-only Claude Code A/B timing. Stdlib only; no model call without --run."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent


def terminate_tree(proc):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_process(argv, cwd, prefix, timeout):
    """Timestamps are host-observed CLI events, NOT server-only TTFT."""
    messages = queue.Queue()
    stats = Stats()
    started = time.perf_counter()
    timed_out = False
    proc = None
    with open(str(prefix) + '.stdout.jsonl', 'w', encoding='utf-8') as raw, \
         open(str(prefix) + '.stderr.log', 'w', encoding='utf-8') as errors:
        try:
            proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=errors,
                                    text=True, encoding='utf-8', errors='replace',
                                    start_new_session=(os.name != 'nt'))
            def reader():
                try:
                    for line in proc.stdout:
                        messages.put((time.perf_counter() - started, line))
                finally:
                    messages.put((None, None))
            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            ended = False
            while not ended:
                remaining = timeout - (time.perf_counter() - started)
                if remaining <= 0:
                    timed_out = True
                    terminate_tree(proc)
                    break
                try:
                    elapsed, line = messages.get(timeout=min(remaining, 0.1))
                except queue.Empty:
                    continue
                if line is None:
                    ended = True
                    continue
                raw.write(line)
                raw.flush()
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    stats.accept(item, elapsed)
            try:
                proc.wait(timeout=max(0.01, timeout - (time.perf_counter() - started)))
            except subprocess.TimeoutExpired:
                timed_out = True
                terminate_tree(proc)
                proc.wait(timeout=15)
            thread.join(timeout=2)
            proc.stdout.close()
        except BaseException:
            if proc is not None and proc.poll() is None:
                terminate_tree(proc)
                proc.wait(timeout=15)
            raise
    return stats.row(time.perf_counter() - started, proc.returncode, timed_out), stats.result

def resolve_claude(explicit=None, windows=None):
    windows = (os.name == 'nt') if windows is None else windows
    found = explicit or shutil.which('claude')
    if not found:
        raise ValueError('Claude CLI not found. Install/configure it first, or pass --claude-bin PATH.')
    path = Path(found).resolve()
    if not path.is_file():
        raise ValueError('Claude executable does not exist: ' + str(path))
    if windows and path.suffix.lower() in ('.cmd', '.bat', '.ps1', ''):
        package = path.parent / 'node_modules' / '@anthropic-ai' / 'claude-code'
        manifest = package / 'package.json'
        if not manifest.is_file():
            raise ValueError('Unsupported Windows wrapper. Pass --claude-bin pointing to the actual Claude .exe.')
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('name') != '@anthropic-ai/claude-code':
            raise ValueError('Unexpected npm package identity.')
        bins = data.get('bin')
        target = bins.get('claude') if isinstance(bins, dict) else bins
        if not isinstance(target, str):
            raise ValueError('Missing Claude npm bin entry.')
        entry = (package / target).resolve()
        if not entry.is_relative_to(package.resolve()):
            raise ValueError('npm bin escapes package directory.')
        if not entry.is_file():
            raise ValueError('npm bin entry not found.')
        if entry.suffix.lower() == '.exe':
            return [str(entry)]
        if entry.suffix.lower() not in ('.js', '.cjs', '.mjs'):
            raise ValueError('Unsupported npm bin type.')
        node = path.parent / 'node.exe'
        node_path = str(node) if node.is_file() else shutil.which('node')
        if not node_path:
            raise ValueError('Node is required by the installed npm Claude package.')
        return [node_path, str(entry)]
    return [str(path)]


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, default=Path.cwd())
    p.add_argument('--model', help='Omit to preserve the current Claude model mapping.')
    p.add_argument('--effort', choices=['low', 'high', 'max'], default='high')
    p.add_argument('--pairs', type=int, default=2)
    p.add_argument('--timeout', type=float, default=300)
    p.add_argument('--max-turns', type=int, default=15)
    p.add_argument('--task-file', type=Path, default=ROOT / 'task.txt')
    p.add_argument('--claude-bin', help='Actual executable or standard npm shim; not a shell alias.')
    p.add_argument('--out', type=Path, default=ROOT / 'results')
    p.add_argument('--run', action='store_true', help='Explicitly authorize real model calls.')
    p.add_argument('--self-test', action='store_true', help='Offline tests only; no CLI or model required.')
    return p


def order(pairs):
    return [v for i in range(pairs) for v in (['baseline', 'lite'] if i % 2 == 0 else ['lite', 'baseline'])]


def command(prefix, args, variant, prompt):
    argv = list(prefix) + ['-p', prompt, '--output-format', 'stream-json', '--verbose',
                          '--include-partial-messages', '--no-session-persistence',
                          '--effort', args.effort, '--max-turns', str(args.max_turns),
                          '--permission-mode', 'default',
                          '--tools', 'Read,Glob,Grep', '--allowedTools', 'Read,Glob,Grep',
                          '--strict-mcp-config', '--mcp-config', str(ROOT / 'empty-mcp.json')]
    if args.model:
        argv += ['--model', args.model]
    if variant == 'lite':
        argv += ['--system-prompt-file', str(ROOT / 'glm-lite-system.txt')]
    return argv


class Stats:
    def __init__(self):
        self.first_model = self.first_text = self.first_tool = None
        self.tools = set()
        self.result = None

    def accept(self, item, elapsed):
        kind = item.get('type')
        if kind == 'stream_event':
            event = item.get('event', {})
            delta = event.get('delta', {})
            if delta.get('type') in ('text_delta', 'thinking_delta') and (delta.get('text') or delta.get('thinking')):
                if self.first_model is None:
                    self.first_model = elapsed
                if delta.get('type') == 'text_delta' and self.first_text is None:
                    self.first_text = elapsed
            block = event.get('content_block', {})
            if block.get('type') == 'tool_use':
                self.tool(block, elapsed)
        if kind == 'assistant':
            for block in item.get('message', {}).get('content', []):
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    self.tool(block, elapsed)
        if kind == 'result':
            self.result = item

    def tool(self, block, elapsed):
        if block.get('id'):
            self.tools.add(block['id'])
        if self.first_tool is None:
            self.first_tool = elapsed

    def row(self, wall, exit_code, timed_out):
        result = self.result or {}
        usage = result.get('usage') or {}
        status = 'success'
        if timed_out:
            status = 'timeout'
        elif exit_code != 0:
            status = 'process_error'
        elif self.result is None:
            status = 'no_result'
        elif result.get('is_error') or result.get('subtype') != 'success':
            status = result.get('subtype') or 'result_error'
        def seconds(key):
            value = result.get(key)
            return value / 1000 if isinstance(value, (int, float)) else None
        return dict(status=status, exit_code=exit_code, wall_s=round(wall, 4),
                    cli_s=seconds('duration_ms'), api_s=seconds('duration_api_ms'),
                    first_model_delta_s=self.first_model, first_text_delta_s=self.first_text,
                    first_tool_request_s=self.first_tool, tool_calls=len(self.tools),
                    turns=result.get('num_turns'), input_tokens=usage.get('input_tokens'),
                    output_tokens=usage.get('output_tokens'),
                    cache_read_tokens=usage.get('cache_read_input_tokens'),
                    cache_write_tokens=usage.get('cache_creation_input_tokens'),
                    cost_usd=result.get('total_cost_usd'),
                    reported_models=';'.join(sorted((result.get('modelUsage') or {}).keys())))


def summarize(rows):
    lines = ['Read-only prompt A/B timing (not a coding-quality benchmark)',
             'success means CLI completion, not independently verified answer correctness.',
             'First-delta times include CLI startup, network, queuing and input processing.',
             'Blank values are unavailable, not zero.']
    for variant in ['baseline', 'lite']:
        group = [r for r in rows if r['variant'] == variant]
        success = [r for r in group if r['status'] == 'success']
        lines.append('\n' + variant + ': completed=' + str(len(success)) + '/' + str(len(group)))
        statuses = {}
        for row in group:
            statuses[row['status']] = statuses.get(row['status'], 0) + 1
        lines.append('statuses=' + json.dumps(statuses))
        if group:
            lines.append('all_attempts_wall_median_s=' + str(round(statistics.median(r['wall_s'] for r in group),4)))
            lines.append('all_attempts_wall_total_s=' + str(round(sum(r['wall_s'] for r in group),4)))
        for key in ['wall_s','api_s','first_model_delta_s','first_text_delta_s','first_tool_request_s',
                    'input_tokens','output_tokens','cache_read_tokens','tool_calls','turns']:
            values = [r[key] for r in success if isinstance(r.get(key),(int,float))]
            lines.append('success_' + key + '_median=' + (str(round(statistics.median(values),4)) if values else 'NA'))
    pairs = {}
    for row in rows:
        pairs.setdefault(row['pair'], {})[row['variant']] = row
    reductions = []
    for pair in pairs.values():
        a, b = pair.get('baseline'), pair.get('lite')
        if a and b and a['status'] == b['status'] == 'success' and a['wall_s'] > 0:
            reductions.append(100 * (a['wall_s'] - b['wall_s']) / a['wall_s'])
    lines.append('\npaired_success_count=' + str(len(reductions)))
    lines.append('paired_wall_reduction_pct_median=' + (str(round(statistics.median(reductions),2)) if reductions else 'NA'))
    lines += ['Positive reduction means lite was faster. Check answer files before interpreting this.',
              'Prefix/OS caches are NOT flushed; alternating order reduces, but does not eliminate, order effects.',
              'Backend effort mapping and true served checkpoint are not verified by this client.']
    return '\n'.join(lines) + '\n'


def save_metrics(out, rows):
    with (out / 'metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out/'summary.txt').write_text(summarize(rows),encoding='utf-8')


def main(argv=None):
    args = parser().parse_args(argv)
    if args.self_test:
        import unittest
        suite = unittest.defaultTestLoader.discover(str(ROOT),pattern='test_bench.py')
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args.pairs < 1 or args.timeout <= 0 or args.max_turns < 1:
        raise ValueError('pairs, timeout and max-turns must be positive.')
    repo = args.repo.resolve()
    if not repo.is_dir():
        raise ValueError('Repository directory not found.')
    prompt = args.task_file.read_text(encoding='utf-8-sig').strip()
    if not prompt:
        raise ValueError('Task is empty.')
    for name in ['glm-lite-system.txt','empty-mcp.json']:
        if not (ROOT/name).is_file():
            raise ValueError('Missing bundle file: '+name)
    variants = order(args.pairs)
    print('Order: ' + ' -> '.join(variants),flush=True)
    print('Model: ' + (args.model or '(inherited)') + '; effort=' + args.effort,flush=True)
    print('Tools: Read,Glob,Grep only; MCP excluded in both conditions.',flush=True)
    print('Existing project/user/managed settings and hooks are inherited. Use a trusted repository.',flush=True)
    if not args.run:
        print('DRY RUN: no model calls, CLI discovery or settings changes. Add --run to measure.')
        return 0
    prefix = resolve_claude(args.claude_bin)
    version = subprocess.run(prefix+['--version'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
    if version.returncode:
        raise ValueError('claude --version failed: ' + version.stderr[:500])
    out = args.out.resolve()/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    out.mkdir(parents=True,exist_ok=False)
    metadata = dict(created_utc=datetime.now(timezone.utc).isoformat(), repo=str(repo),
                    cli_version=version.stdout.strip(), requested_model=args.model,
                    effort=args.effort,pairs=args.pairs,timeout_s=args.timeout,max_turns=args.max_turns,
                    task_sha256=hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
                    lite_sha256=hashlib.sha256((ROOT/'glm-lite-system.txt').read_bytes()).hexdigest(),
                    order=variants, runtime=sys.platform, python=sys.version,
                    settings='inherited; no bare; no MCP; read-only built-in tools',
                    quality='manual review of answer files required')
    (out/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'task.txt').write_text(prompt,encoding='utf-8')
    rows=[]
    for i,variant in enumerate(variants,1):
        print(f'[{i}/{len(variants)}] {variant} running...',flush=True)
        path=out/f'{i:02d}-{variant}'
        attempt_started=time.perf_counter()
        try:
            row,result=run_process(command(prefix,args,variant,prompt),repo,path,args.timeout)
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            row=Stats().row(time.perf_counter()-attempt_started,None,False)
            row['status']='launch_error'
            result=None
            (out/f'{i:02d}-{variant}.error.txt').write_text(str(exc),encoding='utf-8')
        row={'run':i,'pair':(i-1)//2+1,'variant':variant,**row}
        rows.append(row)
        if result is not None:
            (out/f'{i:02d}-{variant}.answer.txt').write_text(str(result.get('result','')),encoding='utf-8')
            (out/f'{i:02d}-{variant}.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        save_metrics(out,rows)
        print(f"  {row['status']} wall={row['wall_s']}s api={row['api_s']}s tools={row['tool_calls']}",flush=True)
    print(summarize(rows))
    print('Saved: ' + str(out))
    return 0 if all(r['status']=='success' for r in rows) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Interrupted; completed runs remain in results.',file=sys.stderr)
        raise SystemExit(130)
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print('ERROR: ' + str(exc),file=sys.stderr)
        raise SystemExit(2)

