"""Mutation tests for the independent prepublication arithmetic audit."""
import copy
import json
from pathlib import Path
import unittest

import pandas as pd

from validate_calculations import audit, validate_calculations


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

    def test_published_snapshot_passes_every_independent_calculation(self):
        report = validate_calculations(ROOT)
        self.assertEqual(report['findings'], [])
        self.assertEqual(len(report['numeric_by_section']), 13)
        self.assertGreater(report['counts']['numeric_cells'], 400)

    def test_wrong_numeric_value_is_rejected_with_row_and_column(self):
        data, raw = self.snapshots()
        row = self.row(data, 'employment', 'PAYEMS')
        row['values'][2] = pd.Series([row['values'][2]]).add(1).iloc[0].item()
        findings = self.results(data, raw)['findings']
        self.assertTrue(any('employment/PAYEMS/Overall/Monthly change' in item for item in findings), findings)

    def test_wrong_observation_date_is_rejected(self):
        data, raw = self.snapshots()
        self.row(data, 'unemployment', 'UNRATE')['values'][4] = '2000-01-01'
        findings = self.results(data, raw)['findings']
        self.assertTrue(any('unemployment/UNRATE/Overall (U-3)/Period' in item for item in findings), findings)

    def test_wrong_display_unit_is_rejected(self):
        data, raw = self.snapshots()
        self.row(data, 'prices', 'GASREGW')['values'][4] = 'USD per barrel'
        findings = self.results(data, raw)['findings']
        self.assertTrue(any('prices/GASREGW/Regular gasoline — gallon/Unit' in item for item in findings), findings)

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
        self.assertTrue(any('Jan 2021–Jan 2025 monthly avg.' in item and 'expected None' in item for item in findings), findings)
        # An honest missing result is accepted. Endpoint changes remain valid.
        self.row(data, 'employment', 'PAYEMS')['values'][6] = None
        self.assertEqual(self.results(data, raw)['findings'], [])

    def test_missing_baseline_requires_null_totals_and_average(self):
        data, raw = self.snapshots()
        raw['series']['PAYEMS']['observations'] = [observation for observation in raw['series']['PAYEMS']['observations']
                                                 if observation['date'] != '2021-01-01']
        self.assertTrue(self.results(data, raw)['findings'])
        row = self.row(data, 'employment', 'PAYEMS')
        for index in [5, 6, 9]:
            row['values'][index] = None
        self.assertEqual(self.results(data, raw)['findings'], [])

    def test_duplicate_series_row_and_placeholder_are_rejected(self):
        data, raw = self.snapshots()
        section = next(section for section in data['sections'] if section['key'] == 'inflation')
        section['rows'].append({'id': None, 'values': ['Unconfigured', None, None, None], 'source': None})
        findings = self.results(data, raw)['findings']
        self.assertTrue(any('row coverage' in item for item in findings), findings)
        self.assertTrue(any('no configured archived source' in item for item in findings), findings)


if __name__ == '__main__':
    unittest.main()
