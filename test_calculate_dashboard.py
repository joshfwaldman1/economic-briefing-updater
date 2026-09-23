"""Meaningful checks for pandas-only observed dashboard calculations."""
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from calculate_dashboard import (
    average_monthly_change, build_dashboard, derive_employment,
    employment_comparison, growth, json_safe, main,
    observation_at_or_before, observation_series, percent_change,
    prewar_baseline, price_comparison,
)

NOW = '2026-09-23T23:02:35.813Z'


def observed(*points):
    return pd.Series([value for _, value in points], index=pd.to_datetime([date for date, _ in points]), dtype='float64')


def raw(series):
    return {'observations': [{'date': date.strftime('%Y-%m-%d'), 'value': value} for date, value in series.items()]}


def monthly(periods=68, start='2021-01-01'):
    return pd.Series(range(periods), index=pd.date_range(start, periods=periods, freq='MS'), dtype='float64').mul(2).add(100)


def definition(series_id, group='employment', **extra):
    return {'id': series_id, 'label': series_id, 'group': group, 'frequency': 'monthly', 'sa': 'SA', 'units': 'Thousands of persons', **extra}


class PandasDashboardTest(unittest.TestCase):
    def test_january_baselines_have_48_and_19_observed_monthly_changes(self):
        stats = employment_comparison(monthly())
        self.assertEqual(stats['period'], '2026-08-01')
        self.assertEqual(stats['level'], 234000)
        self.assertEqual(stats['monthly'], 2000)
        self.assertEqual(stats['total2021To2025'], 96000)
        self.assertEqual(stats['average2021To2025'], 2000)
        self.assertEqual(stats['totalSince2025'], 38000)
        self.assertEqual(stats['averageSince2025'], 2000)
        self.assertEqual(stats['monthsSince2025'], 19)
        self.assertEqual(stats['totalSince2021'], 134000)
        same_month = json_safe(employment_comparison(monthly(49)))
        self.assertEqual(same_month['totalSince2025'], 0)
        self.assertIsNone(same_month['averageSince2025'])

    def test_missing_months_are_never_estimated(self):
        data = monthly().drop(pd.to_datetime(['2023-06-01', '2025-06-01']))
        stats = json_safe(employment_comparison(data))
        self.assertEqual(stats['total2021To2025'], 96000)
        self.assertEqual(stats['totalSince2025'], 38000)
        self.assertIsNone(stats['average2021To2025'])
        self.assertIsNone(stats['averageSince2025'])
        missing_january = json_safe(employment_comparison(data.drop(pd.Timestamp('2021-01-01'))))
        self.assertIsNone(missing_january['totalSince2021'])
        self.assertIsNone(missing_january['total2021To2025'])
        missing_endpoint = observed(('2026-01-01', 100), ('2026-03-01', 110))
        self.assertIsNone(json_safe(growth(missing_endpoint, '2026-03-01', 1)))

    def test_raw_thousands_scaled_once_despite_display_override(self):
        config = {'employment': [definition('PAYEMS', units_override='persons')]}
        data = build_dashboard({'PAYEMS': raw(monthly())}, {}, NOW, config)
        self.assertEqual(data['sections'][0]['rows'][0]['values'][1], 234000)
        self.assertEqual(data['kpis'][0]['value'], 2000)
        self.assertEqual(data['kpis'][0]['source'], 'https://fred.stlouisfed.org/series/PAYEMS')

    def test_auto_sum_uses_common_dates_and_pandas_alignment(self):
        definitions = {key: definition(key, 'manuf_auto', multiplier=1000) for key in ('MFG', 'DEALERS')}
        inputs = {'MFG': observed(('2025-01-01', 10), ('2025-02-01', 11), ('2025-03-01', 12)), 'DEALERS': observed(('2025-01-01', 20), ('2025-02-01', 21))}
        derived = {'id': 'TOTAL', 'label': 'Total auto jobs', 'group': 'manuf_auto', 'sa': 'SA', 'components': ['MFG', 'DEALERS']}
        total = derive_employment(derived, inputs, definitions)
        self.assertEqual(total.index[-1], pd.Timestamp('2025-02-01'))
        self.assertEqual(total.iloc[-1], 32000)
        self.assertEqual(employment_comparison(total, 1)['monthly'], 2000)
        data = build_dashboard({key: raw(value) for key, value in inputs.items()}, {'series': list(definitions.values()), 'derived': [derived]}, NOW)
        total_row = next(row for row in data['sections'][0]['rows'] if row['id'] == 'TOTAL')
        self.assertEqual(total_row['values'][1], 32000)
        self.assertEqual(total_row['values'][-1], '2025-02-01')
        self.assertEqual(len(total_row['sources']), 2)

    def test_inflation_contains_only_observed_mom_and_yoy_and_drops_unconfigured(self):
        cpi = observed(('2025-08-01', 323.1), ('2026-05-01', 333.979), ('2026-06-01', 332.568), ('2026-07-01', 332.813), ('2026-08-01', 334.131))
        config = {'cpi': [definition('CPIAUCSL', 'cpi', units='Index')], 'pce': [{'id': None, 'label': 'Core goods'}]}
        data = build_dashboard({'CPIAUCSL': raw(cpi)}, {}, NOW, config)
        section = next(section for section in data['sections'] if section['key'] == 'inflation')
        self.assertEqual([column['label'] for column in section['columns']], ['Measure / component', 'MoM (%)', 'YoY (%)', 'Period'])
        self.assertEqual(len(section['rows']), 1)
        self.assertAlmostEqual(section['rows'][0]['values'][1], 0.3960181843858157)
        self.assertAlmostEqual(section['rows'][0]['values'][2], cpi.reindex(pd.to_datetime(['2025-08-01', '2026-08-01'])).pct_change(fill_method=None).mul(100).iloc[-1])
        self.assertFalse(any('annualized' in column['label'].lower() for column in section['columns']))

    def test_gdp_reports_observed_quarterly_growth_without_compounding(self):
        data = observed(('2021-01-01', 100), ('2025-01-01', 120), ('2025-04-01', 121), ('2026-01-01', 125), ('2026-04-01', 126))
        catalog = {'series': [definition('GDP', 'gdp', frequency='quarterly', units='Billions of real USD', multiplier=1, sa='SAAR')]}
        section = build_dashboard({'GDP': raw(data)}, catalog, NOW)['sections'][0]
        self.assertEqual(section['columns'][3]['label'], 'QoQ (%)')
        self.assertAlmostEqual(section['rows'][0]['values'][3], 0.8)
        self.assertAlmostEqual(section['rows'][0]['values'][5], 20)
        self.assertEqual(section['rows'][0]['values'][-2], 'SAAR')
        self.assertEqual(section['columns'][-1]['frequency'], 'quarterly')

    def test_zeros_are_preserved_and_zero_denominator_is_missing(self):
        values = observed(('2025-01-01', 0), ('2025-02-01', 5), ('2025-03-01', 0))
        self.assertIsNone(json_safe(percent_change(values, '2025-01-01', '2025-02-01')))
        self.assertEqual(percent_change(values, '2025-02-01', '2025-03-01'), -100)
        self.assertEqual(json_safe({'value': 0, 'missing': float('nan')}), {'value': 0, 'missing': None})
        self.assertEqual(average_monthly_change(values, '2025-01-01', '2025-03-01'), 0)

    def test_prewar_baselines_are_actual_dates_with_complete_monthly_january(self):
        daily = observed(('2026-02-26', 90), ('2026-02-27', 100), ('2026-02-28', 120), ('2026-03-02', 130))
        weekly = observed(('2026-02-23', 3), ('2026-03-02', 3.5))
        monthly_values = observed(('2025-12-01', 9), ('2026-01-01', 10), ('2026-02-01', 11), ('2026-03-01', 12))
        self.assertEqual(prewar_baseline(daily, {'frequency': 'daily'}), pd.Timestamp('2026-02-27'))
        self.assertEqual(prewar_baseline(weekly, {'frequency': 'weekly'}), pd.Timestamp('2026-02-23'))
        self.assertEqual(prewar_baseline(monthly_values, {'frequency': 'monthly'}), pd.Timestamp('2026-01-01'))
        self.assertIsNone(prewar_baseline(monthly_values.drop(pd.Timestamp('2026-01-01')), {'frequency': 'monthly'}))
        self.assertIsNone(prewar_baseline(observed(('2026-01-01', 90)), {'frequency': 'daily'}))

    def test_prewar_tolerance_is_measured_from_start_not_previous_day(self):
        self.assertEqual(prewar_baseline(observed(('2026-02-21', 100)), {'frequency': 'daily'}), pd.Timestamp('2026-02-21'))
        self.assertIsNone(prewar_baseline(observed(('2026-02-20', 100)), {'frequency': 'daily'}))
        self.assertEqual(prewar_baseline(observed(('2026-02-14', 100)), {'frequency': 'weekly'}), pd.Timestamp('2026-02-14'))
        self.assertIsNone(prewar_baseline(observed(('2026-02-13', 100)), {'frequency': 'weekly'}))
        self.assertIsNone(prewar_baseline(observed(('2026-02-28', 100)), {'frequency': 'daily'}))

    def test_rate_changes_are_percentage_points_and_relative_percent_is_distinct(self):
        catalog = {'series': [definition('UNRATE', 'unemployment', units='Percent', multiplier=1)], 'war': ['UNRATE']}
        data = build_dashboard({'UNRATE': raw(observed(('2026-01-01', 4), ('2026-08-01', 4.5)))}, catalog, NOW)
        row = next(section for section in data['sections'] if section['key'] == 'war')['rows'][0]
        self.assertEqual(row['values'][2], '2026-01-01')
        self.assertEqual(row['values'][5], 0.5)
        self.assertEqual(row['values'][6], 12.5)
        self.assertEqual(row['values'][7], 'Percent · SA')
        self.assertEqual(row['frequency'], 'monthly')
        self.assertEqual(row['digits'], {'1': 1, '3': 1, '5': 1})

    def test_prices_keep_dollar_units_nsa_and_exact_weekly_or_monthly_lags(self):
        data = observed(('2025-08-01', 5), ('2026-07-01', 6), ('2026-08-01', 6.5))
        prices = price_comparison(data, {'frequency': 'monthly', 'sa': 'NSA'})
        self.assertEqual(prices['current'], 6.5)
        self.assertEqual(prices['change'], 0.5)
        self.assertAlmostEqual(prices['yearChange'], 30)
        weekly = price_comparison(observed(('2025-09-22', 3), ('2026-09-14', 3.5), ('2026-09-21', 4)), {'frequency': 'weekly'})
        self.assertEqual(weekly['change'], 0.5)
        self.assertAlmostEqual(weekly['yearChange'], 33.33333333333333)
        catalog = {'series': [definition('BEEF', 'prices', units='USD per pound', multiplier=1, sa='NSA')]}
        row = build_dashboard({'BEEF': raw(data)}, catalog, NOW)['sections'][0]['rows'][0]
        self.assertEqual(row['values'][1], 6.5)
        self.assertEqual(row['values'][4], 'USD per pound')
        self.assertEqual(row['values'][6], 'NSA')

    def test_market_calendar_lookup_never_uses_future_or_old_quotes(self):
        data = observed(('2025-12-26', 50), ('2025-12-30', 55), ('2026-01-02', 60))
        self.assertEqual(observation_at_or_before(data, '2025-12-31'), pd.Timestamp('2025-12-30'))
        self.assertIsNone(observation_at_or_before(data, '2026-02-01'))

    def test_budget_sum_requires_every_month_and_reverses_surplus_sign(self):
        data = observed(('2025-10-01', -1000), ('2025-11-01', 200), ('2025-12-01', -500))
        config = {'budget': [definition('MTSDS133FMS', 'budget', sa='NSA', units='USD millions')]}
        rows = build_dashboard({'MTSDS133FMS': raw(data)}, {}, NOW, config)['sections'][0]['rows']
        self.assertEqual(rows[0]['values'][1], 0.5)
        self.assertEqual(rows[1]['values'][1], 1.3)
        self.assertIsNone(rows[2]['values'][1])
        missing = build_dashboard({'MTSDS133FMS': raw(data.drop(pd.Timestamp('2025-11-01')))}, {}, NOW, config)['sections'][0]['rows']
        self.assertIsNone(missing[1]['values'][1])

    def test_validation_rejects_future_nonfinite_and_unordered_observations(self):
        invalid = [
            {'observations': [{'date': '2026-10-01', 'value': 1}]},
            {'observations': [{'date': '2026-01-01', 'value': float('inf')}]},
            {'observations': [{'date': '2026-02-30', 'value': 1}]},
            {'observations': [{'date': '2026-02-01', 'value': 1}, {'date': '2026-01-01', 'value': 1}]},
        ]
        for value in invalid:
            with self.assertRaises(ValueError):
                observation_series(value, 'A', NOW)

    def test_cli_preserves_provenance_and_does_not_replace_output_on_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {'series': {'BEEF': raw(monthly())}, 'retrievedAt': NOW, 'snapshotId': 'snapshot-one'}
            catalog = {'series': [definition('BEEF', 'prices', units='USD per pound', sa='NSA', multiplier=1)]}
            for name, value in [('series.json', payload), ('catalog.json', catalog), ('config.json', {})]:
                (root / name).write_text(json.dumps(value))
            args = ['--series', str(root / 'series.json'), '--catalog', str(root / 'catalog.json'), '--config', str(root / 'config.json'), '--output', str(root / 'data.json')]
            main(args)
            published = (root / 'data.json').read_text()
            result = json.loads(published)
            self.assertEqual(result['retrievedAt'], NOW)
            self.assertEqual(result['snapshotId'], 'snapshot-one')
            self.assertTrue(result['calculationEngine'].startswith('pandas '))
            payload['series']['BEEF']['observations'][0]['value'] = 'bad'
            (root / 'series.json').write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                main(args)
            self.assertEqual((root / 'data.json').read_text(), published)
            self.assertFalse(list(root.glob('*.tmp')))


if __name__ == '__main__':
    unittest.main()
