"""Descriptive paired reporting. No inferred model scores or automatic LLM judge."""
import csv
import difflib
import hashlib
import json
import statistics

from tasks import TASKS

RUBRIC = '''# 블라인드 품질 평가
이 폴더만 리뷰어에게 전달하세요. 외부의 review-key.json은 전달하지 마세요.
파일명에는 실험 조건이 없지만 코드/응답 표현을 통해 조건이 추측될 수 있습니다.

각 항목을 0/1/2점으로 채점하고 파일/라인 근거를 기입하세요.
- 요구사항: 0=핵심 누락, 1=부분 충족, 2=모든 요구 충족.
- 변경 범위: 0=무관/금지 변경, 1=다소 과도, 2=필요한 최소 변경.
- 유지보수성: 0=이해/수정 곤란, 1=보통, 2=명확하고 일관됨.
- 보고 정확성: 0=허위/상충 주장, 1=검증 범위 불명확, 2=실제 검증/한계 명확.
- 테스트 품질: 이번 문제는 공개 테스트 수정 금지이므로 기본 N/A.
  테스트 작성 능력은 별도 문제군으로 평가하세요.

독립 테스트 결과는 기능 정확도의 우선 근거입니다. 이 점수로 기능 실패를 덮지 마세요.
응답의 검증 주장은 response.txt와 evidence.txt를 대조해 평가하세요.
실행 로그가 증명하지 못하는 주장은 검증 불가로 표시하고 추측하지 마세요.
미실행 모델의 점수/응답/증거는 생성하지 않습니다.
'''


def report(runs):
    manifest = json.loads((runs / 'manifest.json').read_text(encoding='utf-8'))
    rows = []
    review = runs / 'blind-review'
    review.mkdir(exist_ok=True)
    (review / 'rubric.md').write_text(RUBRIC, encoding='utf-8', newline='\n')
    mapping = {}
    review_rows = []
    for run_id in manifest['schedule']:
        directory = runs / run_id
        meta = json.loads((directory / 'meta.json').read_text(encoding='utf-8'))
        result_file = directory / 'evaluation.json'
        result = json.loads(result_file.read_text(encoding='utf-8')) if result_file.exists() else None
        execution_file = directory / 'execution.json'
        execution = json.loads(execution_file.read_text(encoding='utf-8')) if execution_file.exists() else None
        from integrity import current
        evaluated = result is not None and current(directory, result)
        valid_exit = execution is not None and execution.get('exit_code') == 0 and not execution.get('timed_out') and not execution.get('api_error', False)
        row = {'run_id': run_id, 'task_id': meta['task_id'], 'condition': meta['condition'], 'repeat': meta['repeat'], 'attempted': execution is not None, 'evaluated': evaluated, 'success': bool(evaluated and execution is not None and result['success'] and valid_exit), 'functional_pass': result['functional_pass'] if evaluated else None, 'protected_changes': ';'.join(result['protected_changes']) if evaluated else '', 'seconds': execution.get('seconds') if execution else None, 'timed_out': execution.get('timed_out') if execution else None, 'input_tokens': execution.get('usage', {}).get('input_tokens') if execution else None, 'output_tokens': execution.get('usage', {}).get('output_tokens') if execution else None}
        rows.append(row)
        if execution is None:
            continue
        blind_id = hashlib.sha256((str(manifest['seed']) + run_id).encode()).hexdigest()[:12]
        mapping[blind_id] = run_id
        bundle = review / blind_id
        bundle.mkdir(exist_ok=True)
        (bundle / 'task.md').write_text((directory / 'workspace' / 'TASK.md').read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
        candidate = directory / 'workspace' / 'solution.py'
        content = candidate.read_text(errors='replace', encoding='utf-8') if candidate.exists() else '[missing solution.py]'
        (bundle / 'solution.py').write_text(content, encoding='utf-8', newline='\n')
        diff = ''.join(difflib.unified_diff(TASKS[meta['task_id']]['starter'].splitlines(keepends=True), content.splitlines(keepends=True), fromfile='before/solution.py', tofile='after/solution.py'))
        (bundle / 'change.diff').write_text(diff, encoding='utf-8', newline='\n')
        (bundle / 'response.txt').write_text(execution.get('response', '[No valid final response captured]'), encoding='utf-8', newline='\n')
        evidence = {'exit_code': execution.get('exit_code'), 'timed_out': execution.get('timed_out'), 'independent_grader': result.get('grader') if evaluated else {'status': 'missing_or_stale_evaluation'}, 'protected_changes': result.get('protected_changes') if result else None, 'note': 'Native JSON final output is not a full tool transcript. Claims about prior checks may remain unverified.'}
        (bundle / 'evidence.txt').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
        review_rows.append({'blind_id': blind_id, 'requirements_0_2': '', 'scope_0_2': '', 'maintainability_0_2': '', 'report_accuracy_0_2': '', 'test_quality': 'N/A', 'evidence': ''})
    summary = {'conditions': {}, 'paired': {'complete_pairs': 0, 'full_only_success': 0, 'baseline_only_success': 0, 'both_success': 0, 'both_fail': 0}, 'note': 'Descriptive pilot results, not a statistical significance claim. No model attempts means null success rate. Pending evaluations are not treated as completed results.'}
    for condition in ('baseline', 'full'):
        scheduled = [r for r in rows if r['condition'] == condition]
        attempted = [r for r in scheduled if r['attempted']]
        completed = [r for r in attempted if r['evaluated']]
        successes = sum(r['success'] for r in completed)
        times = [r['seconds'] for r in completed if r['seconds'] is not None]
        summary['conditions'][condition] = {'scheduled': len(scheduled), 'attempted': len(attempted), 'evaluated_attempts': len(completed), 'pending_evaluations': len(attempted) - len(completed), 'successes': successes, 'success_rate': successes / len(completed) if completed else None, 'median_agent_seconds': statistics.median(times) if times else None, 'timeouts': sum(bool(r['timed_out']) for r in completed)}
    indexed = {(r['task_id'], r['repeat'], r['condition']): r for r in rows}
    for task_id, repeat in sorted({(r['task_id'], r['repeat']) for r in rows}):
        a = indexed[(task_id, repeat, 'baseline')]
        b = indexed[(task_id, repeat, 'full')]
        if not all(r['attempted'] and r['evaluated'] for r in (a, b)):
            continue
        summary['paired']['complete_pairs'] += 1
        key = 'both_success' if a['success'] and b['success'] else 'baseline_only_success' if a['success'] else 'full_only_success' if b['success'] else 'both_fail'
        summary['paired'][key] += 1
    (runs / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    with (runs / 'results.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ['run_id'])
        writer.writeheader()
        writer.writerows(rows)
    # Merge newly completed blind IDs without overwriting existing human scores.
    score_path = review / 'scores.template.csv'
    existing = []
    if score_path.exists():
        with score_path.open(newline='', encoding='utf-8') as stream:
            existing = list(csv.DictReader(stream))
    known = {row['blind_id'] for row in existing}
    merged = existing + [row for row in review_rows if row['blind_id'] not in known]
    with score_path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['blind_id', 'requirements_0_2', 'scope_0_2', 'maintainability_0_2', 'report_accuracy_0_2', 'test_quality', 'evidence'])
        writer.writeheader()
        writer.writerows(merged)
    (runs / 'review-key.json').write_text(json.dumps(mapping, indent=2) + '\n', encoding='utf-8', newline='\n')
    text = '# Benchmark summary\n\n' + summary['note'] + '\n\n'
    for condition, value in summary['conditions'].items():
        text += f'## {condition}\n\n```json\n' + json.dumps(value, indent=2) + '\n```\n\n'
    text += '## Paired outcomes\n\n```json\n' + json.dumps(summary['paired'], indent=2) + '\n```\n'
    (runs / 'summary.md').write_text(text, encoding='utf-8', newline='\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary
