#!/usr/bin/env python3
"""Independent functional checks. Executes candidate Python; NOT a security sandbox."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

SOL = None


class Dedupe(unittest.TestCase):
    def test_order(self):
        self.assertEqual(SOL.stable_unique([3, 1, 3, 2, 1]), [3, 1, 2])
    def test_empty(self):
        self.assertEqual(SOL.stable_unique([]), [])
    def test_unhashable(self):
        self.assertEqual(SOL.stable_unique([[1], {'a': 1}, [1], {'a': 1}]), [[1], {'a': 1}])
    def test_no_mutation(self):
        original = [[2], [1], [2]]
        before = copy.deepcopy(original)
        SOL.stable_unique(original)
        self.assertEqual(original, before)
    def test_equality(self):
        self.assertEqual(SOL.stable_unique([True, 1, False, 0, '1']), [True, False, '1'])
    def test_new_list(self):
        value = [1, 2]
        self.assertIsNot(SOL.stable_unique(value), value)


class Pagination(unittest.TestCase):
    def test_first(self):
        self.assertEqual(SOL.paginate([1, 2, 3], 1, 2), {'items': [1, 2], 'total': 3, 'has_next': True})
    def test_exact_last(self):
        self.assertEqual(SOL.paginate([1, 2, 3, 4], 2, 2), {'items': [3, 4], 'total': 4, 'has_next': False})
    def test_partial_last(self):
        self.assertEqual(SOL.paginate([1, 2, 3], 2, 2), {'items': [3], 'total': 3, 'has_next': False})
    def test_outside(self):
        self.assertEqual(SOL.paginate([1], 100, 2), {'items': [], 'total': 1, 'has_next': False})
    def test_empty(self):
        self.assertEqual(SOL.paginate([], 1, 2), {'items': [], 'total': 0, 'has_next': False})
    def test_invalid(self):
        for value in (0, -1, True, False, 1.0, '1', None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SOL.paginate([], value, 2)
                with self.assertRaises(ValueError):
                    SOL.paginate([], 1, value)
    def test_copy(self):
        value = [1, 2, 3]
        output = SOL.paginate(value, 1, 2)
        output['items'].append(4)
        self.assertEqual(value, [1, 2, 3])


class Money(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(SOL.discounted_total(['10', '20'], '0.1'), '27.00')
    def test_half_up(self):
        self.assertEqual(SOL.discounted_total(['2.675'], '0'), '2.68')
    def test_round_once(self):
        self.assertEqual(SOL.discounted_total(['0.005', '0.005'], '0'), '0.01')
    def test_empty_and_full_discount(self):
        self.assertEqual(SOL.discounted_total([], '0.5'), '0.00')
        self.assertEqual(SOL.discounted_total(['19.99'], '1'), '0.00')
    def test_invalid_price(self):
        for value in ('-1', 'NaN', 'Infinity', '-Infinity', 'bad'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SOL.discounted_total([value], '0')
    def test_invalid_rate(self):
        for value in ('-0.1', '1.01', 'NaN', 'Infinity', 'bad'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SOL.discounted_total(['1'], value)
    def test_no_mutation(self):
        values = ['0.10', '0.20']
        self.assertEqual(SOL.discounted_total(values, '0'), '0.30')
        self.assertEqual(values, ['0.10', '0.20'])


class Retry(unittest.TestCase):
    def test_eventual(self):
        calls = []
        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise ValueError('retry')
            return 9
        self.assertEqual(SOL.retry_call(fn, 3), 9)
        self.assertEqual(len(calls), 3)
    def test_no_extra_call(self):
        calls = []
        def fn():
            calls.append(1)
            return None
        self.assertIsNone(SOL.retry_call(fn, 3))
        self.assertEqual(len(calls), 1)
    def test_other_exception(self):
        calls = []
        def fn():
            calls.append(1)
            raise TypeError('do not retry')
        with self.assertRaises(TypeError):
            SOL.retry_call(fn, 3)
        self.assertEqual(len(calls), 1)
    def test_last_exception_identity(self):
        errors = [ValueError('first'), ValueError('last')]
        calls = []
        def fn():
            index = len(calls)
            calls.append(1)
            raise errors[index]
        with self.assertRaises(ValueError) as caught:
            SOL.retry_call(fn, 2)
        self.assertIs(caught.exception, errors[-1])
        self.assertEqual(len(calls), 2)
    def test_invalid_without_call(self):
        for value in (0, -1, True, False, 1.5, '2', None):
            calls = []
            with self.subTest(value=value), self.assertRaises(ValueError):
                SOL.retry_call(lambda: calls.append(1), value)
            self.assertEqual(calls, [])
    def test_custom_exception(self):
        calls = []
        def fn():
            calls.append(1)
            if len(calls) == 1:
                raise KeyError('retry')
            return 'ok'
        self.assertEqual(SOL.retry_call(fn, 2, (KeyError,)), 'ok')


class Intervals(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual(SOL.merge_intervals([[1, 3], [2, 5]]), [[1, 5]])
    def test_touching(self):
        self.assertEqual(SOL.merge_intervals([[1, 2], [2, 3], [3, 4]]), [[1, 4]])
    def test_contained(self):
        self.assertEqual(SOL.merge_intervals([[1, 10], [2, 3], [1, 10]]), [[1, 10]])
    def test_unsorted_negative(self):
        self.assertEqual(SOL.merge_intervals([[4, 5], [-3, -1], [-2, 0]]), [[-3, 0], [4, 5]])
    def test_empty_and_point(self):
        self.assertEqual(SOL.merge_intervals([]), [])
        self.assertEqual(SOL.merge_intervals([[2, 2]]), [[2, 2]])
    def test_invalid(self):
        with self.assertRaises(ValueError):
            SOL.merge_intervals([[3, 1]])
    def test_no_mutation(self):
        value = [[4, 5], [1, 3], [2, 4]]
        before = copy.deepcopy(value)
        output = SOL.merge_intervals(value)
        self.assertEqual(value, before)
        output[0][0] = -99
        self.assertEqual(value, before)


CLASSES = {'dedupe': Dedupe, 'pagination': Pagination, 'money': Money, 'retry': Retry, 'intervals': Intervals}


def main():
    global SOL
    task_id, candidate = sys.argv[1:]
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CLASSES[task_id])
    expected = suite.countTestCases()
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            spec = importlib.util.spec_from_file_location('candidate', Path(candidate).resolve())
            SOL = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(SOL)
            result = unittest.TextTestRunner(stream=captured, verbosity=2).run(suite)
        output = {'passed': result.wasSuccessful() and result.testsRun == expected and not result.skipped, 'tests_run': result.testsRun, 'skipped': len(result.skipped), 'test_methods': expected, 'failures': len(result.failures), 'errors': len(result.errors), 'detail': captured.getvalue()[-20000:]}
    except Exception as exc:
        output = {'passed': False, 'tests_run': 0, 'test_methods': expected, 'failures': 0, 'errors': 1, 'detail': repr(exc)}
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
