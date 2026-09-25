"""Mutation tests for the independent prepublication arithmetic audit."""
import copy
import json
from pathlib import Path
import unittest

import pandas as pd

from validate_calculations import audit, month_shift, validate_calculations


ROOT = Path(__file__).resolve().parent


class IndependentAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'docs/data.json').read_text())
        cls.raw = json.loads((ROOT / 'docs/series.json').read_text())
        cls.catalog = json.loads((ROOT / 'dashboard_catalog.json').read_text())
        cls.config = json.loads((ROOT / 'config.json').read_text())

    def snapshots(self):
        return copy.deepcopy(self.data), copy.deepcopy(self.raw)

    def results(self, data, raw):
        return audit(data, raw, self.catalog, self.config)

    def row(self, data, key, sid):
        return next(row for section in data['sections'] if section['key'] == key
                    for row in section['rows'] if row['id'] == sid)

    def column(self, data, key, index):
        return next(section['columns'][index]['label'] for section in data['sections'] if section['key'] == key)

    def test_published_snapshot_passes_every_independent_calculation(self):
        report = validate_calculations(ROOT)
        self.assertEqual(report['findings'], [])
        self.assertEqual(len(report['numeric_by_section']), 14)
        self.assertGreater(report['counts']['numeric_cells'], 400)

    def test_wrong_numeric_value_is_rejected_with_row_and_column(self):
        data, raw = self.snapshots()
        row = self.row(data, 'employment', 'PAYEMS')
        row['values'][1] = pd.Series([row['values'][1]]).add(1).iloc[0].item()
        findings = self.results(data, raw)['findings']
        target = 'employment/PAYEMS/Overall/' + self.column(data, 'employment', 1)
        self.assertTrue(any(target in item for item in findings), findings)

    def test_wrong_observation_date_is_rejected(self):
        data, raw = self.snapshots()
        self.row(data, 'unemployment', 'UNRATE')['values'][4] = '2000-01-01'
        findings = self.results(data, raw)['findings']
        target = 'unemployment/UNRATE/Overall (U-3)/' + self.column(data, 'unemployment', 4)
        self.assertTrue(any(target in item for item in findings), findings)

    def test_wrong_display_unit_is_rejected(self):
        data, raw = self.snapshots()
        self.row(data, 'prices', 'GASREGW')['values'][4] = 'USD per barrel'
        findings = self.results(data, raw)['findings']
        target = 'prices/GASREGW/Regular gasoline — gallon/' + self.column(data, 'prices', 4)
        self.assertTrue(any(target in item for item in findings), findings)

    def test_wrong_source_link_is_rejected(self):
        data, raw = self.snapshots()
        self.row(data, 'inflation', 'CPIAUCSL')['source'] = 'https://fred.stlouisfed.org/series/CPILFESL'
        findings = self.results(data, raw)['findings']
        self.assertTrue(any('inflation/CPIAUCSL/CPI · Headline/source' in item for item in findings), findings)

    def test_missing_intervening_month_cannot_preserve_numeric_average(self):
        data, raw = self.snapshots()
        raw['series']['PAYEMS']['observations'] = [observation for observation in raw['series']['PAYEMS']['observations']
                                                 if observation['date'] != '2022-06-01']
        findings = self.results(data, raw)['findings']
        target = self.column(data, 'employment', 5)
        self.assertTrue(any(target in item and 'expected None' in item for item in findings), findings)
        # An honest missing result is accepted. Endpoint changes remain valid.
        self.row(data, 'employment', 'PAYEMS')['values'][5] = None
        self.assertEqual(self.results(data, raw)['findings'], [])

    def test_missing_baseline_requires_null_totals_and_average(self):
        data, raw = self.snapshots()
        raw['series']['PAYEMS']['observations'] = [observation for observation in raw['series']['PAYEMS']['observations']
                                                 if observation['date'] != '2021-01-01']
        self.assertTrue(self.results(data, raw)['findings'])
        row = self.row(data, 'employment', 'PAYEMS')
        for index in [4, 5, 8]:
            row['values'][index] = None
        self.assertEqual(self.results(data, raw)['findings'], [])

    def test_duplicate_series_row_and_placeholder_are_rejected(self):
        data, raw = self.snapshots()
        section = next(section for section in data['sections'] if section['key'] == 'inflation')
        section['rows'].append({'id': None, 'values': ['Unconfigured', None, None, None, None], 'source': None})
        findings = self.results(data, raw)['findings']
        self.assertTrue(any('row coverage' in item for item in findings), findings)
        self.assertTrue(any('no configured archived source' in item for item in findings), findings)

    def test_us_gdp_copies_published_annual_rate_without_recomputing_output(self):
        data, raw = self.snapshots()
        row = self.row(data, 'gdp_us', 'A191RL1Q225SBEA')
        # Simulate mistakenly exposing an unrounded calculation from GDP levels.
        levels = {item['date']: item['value'] for item in raw['series']['GDPC1']['observations']}
        quarter = row['values'][5]
        recomputed = pd.Series([levels[quarter]]).div(pd.Series([levels[month_shift(quarter, -3)]])).pow(4).sub(1).mul(100)
        if recomputed.sub(row['values'][1]).abs().lt(1e-8).all():
            recomputed = recomputed.add(0.001)
        row['values'][1] = recomputed.iloc[0].item()
        findings = self.results(data, raw)['findings']
        self.assertTrue(any('gdp_us/A191RL1Q225SBEA/Real GDP growth/Latest' in item for item in findings), findings)

    def test_gdp_growth_and_level_source_quarters_must_match(self):
        data, raw = self.snapshots()
        observations = raw['series']['A191RL1Q225SBEA']['observations']
        latest = max(item['date'] for item in observations if item['value'] is not None)
        raw['series']['A191RL1Q225SBEA']['observations'] = [item for item in observations if item['date'] != latest]
        findings = self.results(data, raw)['findings']
        self.assertTrue(any('U.S. GDP growth and level publication quarters' in item for item in findings), findings)

    def test_gdp_source_rates_must_agree_with_levels_within_rounding(self):
        data, raw = self.snapshots()
        row = self.row(data, 'gdp_us', 'A191RL1Q225SBEA')
        observation = next(item for item in raw['series']['A191RL1Q225SBEA']['observations'] if item['date'] == row['values'][5])
        changed = pd.Series([observation['value']]).add(0.2).iloc[0].item()
        observation['value'] = changed
        row['values'][1] = changed
        findings = self.results(data, raw)['findings']
        self.assertTrue(any('U.S. GDP source consistency' in item for item in findings), findings)
        self.assertFalse(any('gdp_us/A191RL1Q225SBEA/Real GDP growth/Latest' in item for item in findings), findings)

    def test_g7_staggered_releases_require_one_common_comparison_quarter(self):
        data, raw = self.snapshots()
        rows = next(section['rows'] for section in data['sections'] if section['key'] == 'gdp')
        row = next(row for row in rows if row['id'] == 'CLVMNACSCAB1GQFR')
        quarter = row['values'][6]
        raw['series'][row['id']]['observations'] = [observation for observation in raw['series'][row['id']]['observations']
                                                  if observation['date'] < quarter]
        findings = self.results(data, raw)['findings']
        common_quarter_errors = [item for item in findings if item.startswith('gdp/') and '/Comparison quarter:' in item]
        self.assertEqual(len(common_quarter_errors), 7, findings)
        self.assertFalse(any('gdp_us/' in item for item in findings), findings)

    def test_cpi_annual_values_and_headline_use_nsa_source_only(self):
        data, raw = self.snapshots()
        row = self.row(data, 'inflation', 'CPIAUCSL')
        observations = raw['series']['CPIAUCNS']['observations']
        latest = max(item['date'] for item in observations if item['value'] is not None)
        for observation in observations:
            if observation['date'] in {latest, row['values'][3]}:
                observation['value'] = pd.Series([observation['value']]).add(0.1).iloc[0].item()
        findings = self.results(data, raw)['findings']
        annual_target = 'inflation/CPIAUCSL/CPI · Headline/' + self.column(data, 'inflation', 2)
        monthly_target = 'inflation/CPIAUCSL/CPI · Headline/' + self.column(data, 'inflation', 1)
        self.assertTrue(any(annual_target in item for item in findings), findings)
        self.assertTrue(any('KPI/CPIAUCNS/value' in item for item in findings), findings)
        self.assertFalse(any(monthly_target in item for item in findings), findings)

    def test_cpi_annual_adjustment_and_source_links_are_checked(self):
        data, raw = self.snapshots()
        row = self.row(data, 'inflation', 'CPIAUCSL')
        row['values'][4] = 'SA'
        row['sources'] = [{'label': 'Monthly: SA', 'url': row['source']}]
        findings = self.results(data, raw)['findings']
        self.assertTrue(any('12-month adjustment' in item for item in findings), findings)
        self.assertTrue(any('monthly and annual source links' in item for item in findings), findings)


if __name__ == '__main__':
    unittest.main()
