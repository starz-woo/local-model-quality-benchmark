"""Benchmark author data. Never copied into candidate workspaces."""
TASKS = {
    'dedupe': {
        'request': '''solution.py의 stable_unique(items)를 수정하세요.
입력 순서를 유지하며 동등한 항목은 최초 항목만 남긴 새 리스트를 반환하세요.
정수/문자열뿐 아니라 리스트·딕셔너리 같은 비해시 가능 항목도 지원해야 합니다.
입력 및 내부 항목을 변경하지 마세요. 동등성은 Python == 기준입니다.''',
        'starter': 'def stable_unique(items):\n    return list(set(items))\n',
        'public': '''import unittest
from solution import stable_unique
class PublicTests(unittest.TestCase):
    def test_order(self):
        self.assertEqual(stable_unique([3, 1, 3, 2]), [3, 1, 2])
    def test_empty(self):
        self.assertEqual(stable_unique([]), [])
''',
        'reference': '''def stable_unique(items):
    result = []
    for item in items:
        if item not in result:
            result.append(item)
    return result
''',
    },
    'pagination': {
        'request': '''solution.py의 paginate(items, page, page_size)를 수정하세요.
page는 1부터 시작합니다. page/page_size는 bool을 제외한 양의 int이며 그 외는 ValueError.
반환 형식: {"items": 선택 부분의 새 리스트, "total": 전체 입력 개수, "has_next": 다음 페이지 존재 여부}.
범위 밖 페이지는 빈 리스트이며 빈 입력도 허용합니다. 입력 리스트를 변경하지 마세요.''',
        'starter': '''def paginate(items, page, page_size):
    start = page * page_size
    return {"items": items[start:start + page_size], "total": len(items), "has_next": start < len(items)}
''',
        'public': '''import unittest
from solution import paginate
class PublicTests(unittest.TestCase):
    def test_first_page(self):
        self.assertEqual(paginate([1, 2, 3], 1, 2), {"items": [1, 2], "total": 3, "has_next": True})
    def test_invalid(self):
        with self.assertRaises(ValueError):
            paginate([], 0, 2)
''',
        'reference': '''def paginate(items, page, page_size):
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (page, page_size)):
        raise ValueError("positive integer required")
    start = (page - 1) * page_size
    return {"items": list(items[start:start + page_size]), "total": len(items), "has_next": start + page_size < len(items)}
''',
    },
    'money': {
        'request': '''solution.py의 discounted_total(prices, rate)를 수정하세요.
prices는 음이 아닌 유한 십진수 문자열 목록이고 rate는 0 이상 1 이하의 유한 십진수 문자열입니다.
Decimal로 정확히 합산한 뒤 할인율 rate를 적용하고, 마지막에 한 번만 소수 둘째 자리로
ROUND_HALF_UP 반올림한 문자열을 반환하세요. 빈 목록은 "0.00".
잘못된 숫자 문자열/음수 가격/범위 밖 할인율/NaN/Infinity는 ValueError.
입력은 변경하지 마세요. 숫자 크기는 Decimal 기본 정밀도로 처리 가능한 범위입니다.''',
        'starter': '''def discounted_total(prices, rate):
    return str(round(sum(float(x) for x in prices) * (1 - float(rate)), 2))
''',
        'public': '''import unittest
from solution import discounted_total
class PublicTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(discounted_total(["10.00", "20.00"], "0.10"), "27.00")
    def test_half_up(self):
        self.assertEqual(discounted_total(["1.005"], "0"), "1.01")
''',
        'reference': '''from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
def discounted_total(prices, rate):
    try:
        values = [Decimal(x) for x in prices]
        discount = Decimal(rate)
        if not discount.is_finite() or not 0 <= discount <= 1:
            raise ValueError("invalid rate")
        if any(not value.is_finite() or value < 0 for value in values):
            raise ValueError("invalid price")
        total = sum(values, Decimal(0)) * (Decimal(1) - discount)
        return format(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
''',
    },
    'retry': {
        'request': '''solution.py의 retry_call(fn, attempts, retry_on=(ValueError,))를 수정하세요.
attempts는 최초 호출을 포함한 최대 호출 횟수입니다. bool을 제외한 양의 int가 아니면
fn을 호출하지 않고 ValueError. retry_on에 해당하는 예외만 재시도하세요.
성공하면 반환값(None 포함)을 그대로 반환하고 더 호출하지 마세요.
다른 예외는 즉시 전파하며, 재시도를 소진하면 마지막 예외 객체 자체를 다시 발생시키세요.
sleep이나 외부 의존성은 추가하지 마세요.''',
        'starter': '''def retry_call(fn, attempts, retry_on=(ValueError,)):
    return fn()
''',
        'public': '''import unittest
from solution import retry_call
class PublicTests(unittest.TestCase):
    def test_eventual_success(self):
        calls = []
        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise ValueError("retry")
            return 42
        self.assertEqual(retry_call(fn, 2), 42)
        self.assertEqual(len(calls), 2)
    def test_invalid(self):
        with self.assertRaises(ValueError):
            retry_call(lambda: 1, 0)
''',
        'reference': '''def retry_call(fn, attempts, retry_on=(ValueError,)):
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts <= 0:
        raise ValueError("positive integer required")
    for index in range(attempts):
        try:
            return fn()
        except retry_on:
            if index == attempts - 1:
                raise
''',
    },
    'intervals': {
        'request': '''solution.py의 merge_intervals(intervals)를 수정하세요.
유한 정수 start/end 쌍 목록을 받아, 정렬된 list[list[int]] 형태로 합쳐 반환하세요.
겹치거나 경계가 맞닿은 구간도 병합합니다. 포함된 구간/중복/음수/빈 입력을 지원하세요.
start > end인 구간은 ValueError. 입력과 내부 구간은 변경하지 마세요.
입력 형식과 정수 여부 자체는 유효하다고 가정해도 됩니다.''',
        'starter': '''def merge_intervals(intervals):
    intervals.sort()
    return intervals
''',
        'public': '''import unittest
from solution import merge_intervals
class PublicTests(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual(merge_intervals([[1, 3], [2, 4]]), [[1, 4]])
    def test_empty(self):
        self.assertEqual(merge_intervals([]), [])
''',
        'reference': '''def merge_intervals(intervals):
    if any(start > end for start, end in intervals):
        raise ValueError("reversed interval")
    result = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result
''',
    },
}

# Shared prompt does not tell the model which experimental condition it is in.
COMMON = '''

solution.py만 수정하세요. 공개 테스트/지침/설정을 변경하거나 검사 수준을 낮추지 마세요.
표준 라이브러리만 사용하세요. 필요한 검증을 수행하고 실제 결과와 미검증 사항을 보고하세요.
공개 검사: {public_test_command}

비대화형 실행 계약 (두 비교 조건 공통):
- 현재 작업 디렉터리는 이미 workspace입니다. cd 또는 셸 실행기를 덧붙이지 마세요.
- 공개 검사는 위 명령을 그대로 하나의 Bash 또는 PowerShell 도구 호출로 실행하세요.
- &&, ;, 파이프, 리다이렉션, here-document, 인라인 Python을 결합한 복합 명령을 만들지 마세요.
- solution.py 외에는 파일을 추가/삭제/변경하지 마세요. 추가 검사 스크립트를 만들거나 실행하지 마세요.
- 비대화형이라 사용자가 추가 승인을 응답할 수 없습니다. 승인 요구/거부된 명령을 형태만 바꿔 반복하지 마세요.
- 위 공개 검사 단일 명령도 승인 거부되면 작업을 멈추고 BLOCKED와 거부 이유를 최종 응답으로 보고하세요.
- 공개 검사 결과와 미검증 사항을 최종 응답으로 보고한 뒤 종료하세요. 통과를 추측하지 마세요.
'''
