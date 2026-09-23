"""Focused calculation and parsing checks. Run: python3 -m unittest test_chartbook.py"""
import unittest
from update_chartbook import month_index, derive_table, parse_bls_data, format_value


def point(value, note=None):
    return {'value': value, 'provider': 'BLS', 'footnotes': [note] if note else []}


class ChartbookTests(unittest.TestCase):
    def test_month_change_uses_calendar_offset(self):
        jan = month_index(2026, 1)
        data = {'a': {jan: point(100), jan+2: point(140), jan+3: point(130)}}
        result = derive_table({'components': ['a'], 'lag_months': 1}, data)
        self.assertNotIn(jan+2, result)  # Missing February must not create a 40 change.
        self.assertEqual(result[jan+3]['value'], -10)

    def test_annual_change_and_component_intersection(self):
        jan = month_index(2025, 1)
        data = {'a': {jan: point(100), jan+12: point(140), jan+13: point(150)},
                'b': {jan: point(50), jan+12: point(65)}}
        result = derive_table({'components': ['a', 'b'], 'lag_months': 12}, data)
        self.assertEqual(result[jan+12]['value'], 55)
        self.assertNotIn(jan+13, result)

    def test_parse_excludes_annual_average_and_nonfinite(self):
        response = {'status': 'REQUEST_SUCCEEDED', 'Results': {'series': [{'seriesID': 'a', 'data': [
            {'year': '2026', 'period': 'M01', 'value': '1,234', 'footnotes': [{'code': 'P', 'text': 'preliminary'}]},
            {'year': '2026', 'period': 'M13', 'value': '99'},
            {'year': '2026', 'period': 'M02', 'value': 'NaN'},
            {'year': '2024', 'period': 'M01', 'value': '1'},
        ]}]}}
        parsed = parse_bls_data(response, ['a'], 2026, 2026)['a']
        self.assertEqual(list(parsed), [month_index(2026, 1)])
        self.assertEqual(parsed[month_index(2026, 1)]['value'], 1234)
        self.assertEqual(format_value(parsed[month_index(2026, 1)], 0), '1234*')

    def test_provisional_prior_used_by_change(self):
        jan = month_index(2026, 1)
        data = {'a': {jan: point(100, {'code': 'P'}), jan+1: point(101)}}
        result = derive_table({'components': ['a'], 'lag_months': 1}, data)
        self.assertEqual(format_value(result[jan+1], 0), '1*')

    def test_no_imputed_missing_values(self):
        self.assertEqual(format_value(None, 1), '\u2014')
        self.assertEqual(format_value(point(-0.00000000001), 1), '0.0')

    def test_api_failure_raises(self):
        with self.assertRaises(RuntimeError):
            parse_bls_data({'status': 'REQUEST_FAILED', 'message': ['limit']}, ['a'], 2026, 2026)

if __name__ == '__main__':
    unittest.main()
