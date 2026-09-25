#!/usr/bin/env python3
"""Independent arithmetic audit of the published economic dashboard.

Never imports production calculations. This checks transformations against the
archived observations, not whether an upstream provider's observations are correct.
All economic calculations use pandas, independently of the publishing engine.
"""
import argparse
import calendar
from collections import Counter
from datetime import date, timedelta
import json
import math
from numbers import Real
from pathlib import Path
import sys
import pandas as pd


def month_shift(day, amount):
    day = date.fromisoformat(day)
    serial = day.year * 12 + day.month - 1 + amount
    year, month0 = divmod(serial, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1])).isoformat()


def days_shift(day, amount):
    return (date.fromisoformat(day) + timedelta(days=amount)).isoformat()


def month_distance(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return (b.year - a.year) * 12 + b.month - a.month


def scalar(value):
    """Convert a pandas missing result into the published JSON null convention."""
    return None if pd.isna(value) else float(value)


def scaled(value, multiplier):
    return scalar(pd.Series([value], dtype='float64').mul(multiplier).iloc[0])


def subtract(a, b):
    return scalar(pd.Series([a], dtype='float64').sub(pd.Series([b], dtype='float64')).iloc[0])


def ratio_change(a, b):
    if a is None or b is None or b == 0:
        return None
    return scalar(pd.Series([a], dtype='float64').div(pd.Series([b], dtype='float64')).sub(1).mul(100).iloc[0])


def consecutive_months(values, end, count):
    return [values.get(month_shift(end, -i)) for i in range(count)]


def complete_sum(values):
    return None if not values else scalar(pd.Series(values, dtype='float64').sum(min_count=len(values)))


def monthly_average_change(values, start, end):
    months = month_distance(start, end)
    if months <= 0:
        return None
    observations = pd.Series(values, dtype='float64').reindex(pd.date_range(start, end, freq='MS').strftime('%Y-%m-%d'))
    if len(observations) != months + 1 or observations.isna().any():
        return None
    return scalar(observations.diff().iloc[1:].mean(skipna=False))


def preceding(values, cutoff, tolerance, strictly_before=False):
    candidates = [day for day, value in values.items()
                  if value is not None and (day < cutoff if strictly_before else day <= cutoff)]
    if not candidates:
        return None, None
    latest = max(candidates)
    if (date.fromisoformat(cutoff) - date.fromisoformat(latest)).days > tolerance:
        return None, None
    return latest, values[latest]


def audit(data, raw, catalog, config):
    """Return counts and findings. All four arguments are decoded JSON objects."""
    issues = []
    counts = Counter()
    section_counts = Counter()
    raw_series = raw['series']
    definitions = {}
    for group in config.values():
        if isinstance(group, list):
            for item in group:
                if isinstance(item, dict) and item.get('id'):
                    definitions[item['id']] = dict(item)
    definitions.update({item['id']: item for item in catalog['series']})
    derived = {item['id']: item for item in catalog['derived']}
    definitions.update(derived)
    values_by_id = {}

    def check(actual, expected, where, kind=None):
        if isinstance(expected, Real) and not isinstance(expected, bool):
            if actual is None or isinstance(actual, bool) or not isinstance(actual, Real):
                issues.append(f'{where}: expected numeric {expected}, got {actual!r}')
                return
            if not math.isfinite(actual) or not math.isfinite(expected):
                issues.append(f'{where}: non-finite number {actual!r} / {expected}')
                return
            if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-8):
                issues.append(f'{where}: expected {expected}, got {actual}')
            counts[kind or 'numeric_cells'] += 1
        else:
            if actual != expected:
                issues.append(f'{where}: expected {expected!r}, got {actual!r}')
            counts[kind or ('null_cells' if expected is None else 'text_or_date_cells')] += 1

    for field in ['snapshotId', 'retrieved', 'retrievedAt']:
        check(data.get(field), raw.get(field), f'snapshot.{field}', 'snapshot_checks')

    for sid, record in raw_series.items():
        observed = {}
        last_day = None
        for observation in record['observations']:
            day, value = observation['date'], observation['value']
            try:
                date.fromisoformat(day)
            except (ValueError, TypeError):
                issues.append(f'{sid}: invalid observation date {day!r}')
                continue
            if day in observed:
                issues.append(f'{sid}: duplicated observation date {day}')
            if last_day is not None and day <= last_day:
                issues.append(f'{sid}: unsorted observation dates {last_day}, {day}')
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                issues.append(f'{sid}: invalid observation value at {day}: {value!r}')
                continue
            observed[day] = value
            last_day = day
        values_by_id[sid] = observed
        check(record.get('id'), sid, f'{sid}.id', 'source_checks')
        url = f'https://fred.stlouisfed.org/series/{sid}'
        check(record.get('source'), url, f'{sid}.source', 'source_checks')
        check(record.get('sourceUrl'), url, f'{sid}.sourceUrl', 'source_checks')
        if sid in definitions:
            definition = definitions[sid]
            for field in ['units', 'sa']:
                # Workbook-only metadata can differ in case from canonical catalog.
                check(str(record.get(field, '')).lower(), str(definition.get(field, '')).lower(), f'{sid}.{field}', 'metadata_checks')
            check(record.get('frequency'), str(definition.get('frequency', 'monthly')).lower(), f'{sid}.frequency', 'metadata_checks')
        counts['source_observations'] += len(observed)

    for sid, definition in derived.items():
        if definition['operation'] != 'sum':
            issues.append(f'{sid}: unsupported derived operation {definition["operation"]!r}')
            continue
        components = definition['components']
        if any(component not in values_by_id for component in components):
            issues.append(f'{sid}: missing component series')
            continue
        common_dates = set.intersection(*(set(day for day, value in values_by_id[c].items() if value is not None) for c in components))
        # Current auto inputs are published in thousands; never rely on a
        # potentially incorrect dashboard multiplier when deriving people.
        for component in components:
            if 'thousand' not in raw_series[component]['units'].lower():
                issues.append(f'{sid}: unexpected raw component units for {component}')
        inputs = pd.DataFrame({component: pd.Series(values_by_id[component], dtype='float64') for component in components})
        values_by_id[sid] = inputs.loc[sorted(common_dates)].mul(1000).sum(axis=1, min_count=len(components)).to_dict()

    def latest(sid):
        values = values_by_id.get(sid, {})
        dates = [day for day, value in values.items() if value is not None]
        if not dates:
            return values, None, None
        day = max(dates)
        return values, day, values[day]

    def ids(group):
        return [item['id'] for item in config[group] if item.get('id')]

    gdp_levels, gdp_quarter, gdp_level = latest('GDPC1')
    gdp_rates, gdp_rate_quarter, gdp_rate = latest('A191RL1Q225SBEA')
    check(gdp_rate_quarter, gdp_quarter, 'U.S. GDP growth and level publication quarters', 'metadata_checks')
    displayed_gdp_quarters = [month_shift(gdp_quarter, offset) for offset in (0, -3, -12)] if gdp_quarter else []
    if not displayed_gdp_quarters:
        issues.append('U.S. GDP source consistency: required growth rate or quarterly level missing')
    for quarter in displayed_gdp_quarters:
        level = gdp_levels.get(quarter)
        preceding_level = gdp_levels.get(month_shift(quarter, -3))
        rate = gdp_rates.get(quarter)
        if level is None or preceding_level in (None, 0) or rate is None:
            issues.append(f'U.S. GDP source consistency: required growth rate or quarterly level missing at {quarter}')
            continue
        # Only a cross-source validation: never substitute this recomputed rate
        # for BEA's directly published annual rate in the dashboard output.
        implied_annual_rate = pd.Series([level], dtype='float64').div(
            pd.Series([preceding_level], dtype='float64')).pow(4).sub(1).mul(100)
        published_rate = pd.Series([rate], dtype='float64')
        if not published_rate.sub(implied_annual_rate).abs().le(0.055).all():
            issues.append(f'U.S. GDP source consistency: published annual rate {rate} differs from '
                          f'quarterly levels beyond 0.055 percentage points at {quarter}')
        counts['source_consistency_checks'] += 1

    inflation_comparisons = catalog.get('inflationComparisons', {})
    expected_inflation_comparisons = {
        'CPIAUCSL': 'CPIAUCNS', 'CPILFESL': 'CPILFENS',
        'CUSR0000SACL1E': 'CUUR0000SACL1E', 'CUSR0000SASLE': 'CUUR0000SASLE',
        'CUSR0000SAH1': 'CUUR0000SAH1', 'CPIUFDSL': 'CPIUFDNS', 'CPIENGSL': 'CPIENGNS',
    }
    check(inflation_comparisons, expected_inflation_comparisons,
          'CPI unadjusted annual-comparison source mappings', 'source_checks')
    expected_ids = {
        'employment': ids('employment'), 'unemployment': ids('unemployment'),
        'inflation': ids('cpi') + ids('pce'),
        'prices': [x['id'] for x in catalog['series'] if x.get('group') == 'prices'],
        'manufacturing': ['MANEMP'] + ids('manufacturing') + list(derived),
        'gdp': [x['id'] for x in catalog['series'] if x.get('group') == 'gdp'],
        'gdp_us': ['A191RL1Q225SBEA', 'GDPC1'],
        'applications': ids('applications'), 'claims': ids('claims'),
        'markets': ids('markets'), 'budget': ['MTSDS133FMS'] * 3 + ['FYFSGDA188S'],
        'participation': ids('participation'),
        'context': ['JTSJOL', 'JTSQUR', 'U6RATE'] + ids('wages'),
        'war': list(catalog['war']) + ['CPIAUCSL', 'CPILFESL', 'PCEPI', 'PCEPILFE', 'PAYEMS', 'UNRATE', 'ICSA'],
    }
    required_sources = set().union(*expected_ids.values()) - set(derived)
    required_sources.update(component for definition in derived.values() for component in definition['components'])
    required_sources.update(expected_inflation_comparisons.values())
    check(set(raw_series), required_sources, 'raw source coverage', 'coverage_checks')
    counts['source_series'] = len(raw_series)
    gdp_date_sets = [set(day for day, value in values_by_id.get(sid, {}).items() if value is not None)
                     for sid in expected_ids['gdp']]
    gdp_common_dates = set.intersection(*gdp_date_sets) if gdp_date_sets else set()
    gdp_comparison_quarter = max(gdp_common_dates) if gdp_common_dates else None
    if gdp_comparison_quarter is None:
        issues.append('G7 GDP: no common observed comparison quarter across all economies')
    check(Counter(t['key'] for t in data['sections']), Counter(expected_ids.keys()), 'section coverage', 'coverage_checks')
    for table in data['sections']:
        key = table['key']
        if key not in expected_ids:
            issues.append(f'{key}: unknown section cannot be independently audited')
            continue
        check(Counter(r['id'] for r in table['rows']), Counter(expected_ids[key]), f'{key}: row coverage', 'coverage_checks')
        if key == 'inflation':
            check([column['label'] for column in table['columns']],
                  ['Measure / component', '1-month change (%, SA)', '12-month change (%)',
                   'Latest month', '12-month adjustment'],
                  'inflation/columns', 'metadata_checks')
        if key == 'gdp':
            check([column['label'] for column in table['columns']],
                  ['Economy', 'Quarterly change (%, not annualized)', '4-quarter change (%)',
                   'Q1 2021–Q1 2025 cumulative change (%)', 'Since Q1 2025 cumulative change (%)',
                   'Since Q1 2021 cumulative change (%)', 'Comparison quarter'],
                  'gdp/columns', 'metadata_checks')
        if key == 'gdp_us':
            check([column['label'] for column in table['columns']],
                  ['Measure', 'Latest', 'Previous quarter', 'Same quarter a year earlier',
                   'Unit / convention', 'Quarter'], 'gdp_us/columns', 'metadata_checks')
        for row in table['rows']:
            sid = row['id']
            where = f'{key}/{sid}/{row["values"][0]}'
            if not sid or sid not in values_by_id:
                issues.append(f'{where}: no configured archived source series')
                continue
            values, end, current = latest(sid)
            if key == 'gdp':
                end = gdp_comparison_quarter
                current = values.get(end)
            if end is None:
                issues.append(f'{where}: no finite observed values')
                continue
            definition = definitions[sid]
            expected_source = definition['source'] if sid in derived else f'https://fred.stlouisfed.org/series/{sid}'
            check(row.get('source'), expected_source, where + '/source', 'source_checks')
            check(row.get('sa'), definition.get('sa'), where + '/sa', 'metadata_checks')
            frequency = definition.get('frequency', 'monthly').lower()
            check(row.get('frequency'), frequency, where + '/frequency', 'metadata_checks')
            expected = {}
            expected_label = definition['label']
            if key == 'inflation':
                expected_label = ('CPI' if sid in ids('cpi') else 'PCE') + ' · ' + expected_label
            elif key == 'gdp_us' and sid == 'GDPC1':
                expected_label = 'Real GDP level'
            elif key == 'war':
                expected_label = {
                    'CPIAUCSL': 'CPI price index', 'CPILFESL': 'Core CPI price index',
                    'PCEPI': 'PCE price index', 'PCEPILFE': 'Core PCE price index',
                    'PAYEMS': 'Total nonfarm payroll jobs', 'UNRATE': 'Unemployment rate (U-3)',
                    'ICSA': 'Initial jobless claims',
                }.get(sid, expected_label)
            if key != 'budget':
                check(row['values'][0].casefold(), expected_label.casefold(), where + '/label', 'metadata_checks')
            if key in ['employment', 'manufacturing']:
                scale = 1 if sid in derived else 1000
                if sid not in derived and 'thousand' not in raw_series[sid]['units'].lower():
                    issues.append(where + ': raw employment units must be thousands')
                levels = pd.Series(values, dtype='float64').mul(scale).to_dict()
                levels = {day: scalar(value) for day, value in levels.items()}
                cur = levels[end]
                start21, start25 = levels.get('2021-01-01'), levels.get('2025-01-01')
                expected = {1: cur, 2: subtract(cur, levels.get(month_shift(end, -1))),
                            3: monthly_average_change(levels, month_shift(end, -3), end),
                            4: monthly_average_change(levels, month_shift(end, -12), end),
                            5: subtract(start25, start21),
                            6: monthly_average_change(levels, '2021-01-01', '2025-01-01'),
                            7: subtract(cur, start25),
                            8: monthly_average_change(levels, '2025-01-01', end),
                            9: subtract(cur, start21), 10: definition['sa'], 11: end}
                if key == 'employment':
                    expected = {index - 1: value for index, value in expected.items() if index > 1}
            elif key in ['unemployment', 'participation']:
                expected = {1: current, 2: subtract(current, values.get(month_shift(end, -1))),
                            3: subtract(current, values.get(month_shift(end, -12))), 4: end}
            elif key == 'inflation':
                annual_sid = expected_inflation_comparisons.get(sid, sid)
                annual_values = values_by_id.get(annual_sid, {})
                annual_adjustment = 'NSA' if sid in expected_inflation_comparisons else 'SA'
                expected = {1: ratio_change(current, values.get(month_shift(end, -1))),
                            2: ratio_change(annual_values.get(end), annual_values.get(month_shift(end, -12))),
                            3: end, 4: annual_adjustment}
                if sid in expected_inflation_comparisons:
                    check(Counter(source.get('url') for source in row.get('sources', [])),
                          Counter([f'https://fred.stlouisfed.org/series/{sid}',
                                   f'https://fred.stlouisfed.org/series/{annual_sid}']),
                          where + '/monthly and annual source links', 'source_checks')
            elif key == 'prices':
                prior = days_shift(end, -7) if frequency == 'weekly' else month_shift(end, -1)
                year_ago = days_shift(end, -364) if frequency == 'weekly' else month_shift(end, -12)
                expected = {1: current, 2: subtract(current, values.get(prior)), 3: ratio_change(current, values.get(year_ago)),
                            4: definition['units'], 5: frequency, 6: definition['sa'], 7: end}
            elif key == 'gdp':
                expected = {1: ratio_change(current, values.get(month_shift(end, -3))),
                            2: ratio_change(current, values.get(month_shift(end, -12))),
                            3: ratio_change(values.get('2025-01-01'), values.get('2021-01-01')),
                            4: ratio_change(current, values.get('2025-01-01')),
                            5: ratio_change(current, values.get('2021-01-01')), 6: end}
            elif key == 'gdp_us':
                expected = {1: current, 2: values.get(month_shift(end, -3)),
                            3: values.get(month_shift(end, -12)),
                            4: definition['units'] + ' · ' + definition['sa'], 5: end}
            elif key == 'applications':
                expected = {1: current, 2: ratio_change(current, values.get(month_shift(end, -1))),
                            3: ratio_change(current, values.get(month_shift(end, -12))), 4: end}
            elif key == 'claims':
                expected = {1: current, 2: values.get(days_shift(end, -7)), 3: values.get(days_shift(end, -364)), 4: end}
            elif key == 'markets':
                prior_month = preceding(values, month_shift(end, -1), 7)[1]
                prior_year = preceding(values, month_shift(end, -12), 7)[1]
                prior_year_end = preceding(values, f'{int(end[:4])-1}-12-31', 7)[1]
                expected = {1: current, 2: ratio_change(current, prior_month), 3: ratio_change(current, prior_year_end),
                            4: ratio_change(current, prior_year), 5: end}
            elif key == 'budget':
                if sid == 'FYFSGDA188S':
                    expected = {1: scaled(current, -1), 2: '% of GDP', 3: 'FY ' + end[:4]}
                else:
                    label = row['values'][0]
                    if label == 'Monthly deficit':
                        total = current
                        first_month = end
                    elif label == 'Fiscal year to date deficit':
                        fy_year = int(end[:4]) if int(end[5:7]) >= 10 else int(end[:4]) - 1
                        first_month = f'{fy_year}-10-01'
                        total = complete_sum(consecutive_months(values, end, month_distance(first_month, end) + 1))
                    elif label == 'Trailing 12 months deficit':
                        total = complete_sum(consecutive_months(values, end, 12))
                        first_month = month_shift(end, -11)
                    else:
                        issues.append(where + ': unsupported budget measure')
                        continue
                    end_label = date.fromisoformat(end).strftime('%b %Y')
                    period_label = (date.fromisoformat(first_month).strftime('%b %Y') + '–' + end_label
                                    if first_month != end else end_label)
                    expected = {1: scaled(total, -0.001), 2: 'USD billions', 3: period_label}
            elif key == 'context':
                expected = {1: current, 2: definition['units'], 3: end}
            elif key == 'war':
                cutoff = catalog['warBaseline']
                check(data.get('warStart'), cutoff, where + '/warStart', 'metadata_checks')
                if frequency == 'monthly':
                    baseline = month_shift(cutoff[:7] + '-01', -1)
                    before = values.get(baseline)
                    if before is None:
                        baseline = None
                else:
                    baseline, before = preceding(values, cutoff, 7 if frequency == 'daily' else 14, strictly_before=True)
                scale = 1000 if sid == 'PAYEMS' else 1
                before = scaled(before, scale)
                after = scaled(current, scale)
                units = 'Jobs' if sid == 'PAYEMS' else definition['units']
                change_unit = ('Percentage points' if units in ['Percent', '%'] else
                               'Index points' if units.startswith('Index') else
                               'Claims' if sid == 'ICSA' else units)
                expected = {1: before, 2: baseline, 3: after, 4: end,
                            5: subtract(after, before), 6: ratio_change(after, before),
                            7: units + ' · ' + definition['sa'], 8: change_unit}
            for index, expectation in expected.items():
                label = table['columns'][index]['label']
                actual = row['values'][index] if index < len(row['values']) else '<missing>'
                check(actual, expectation, where + '/' + label)
                if isinstance(expectation, Real):
                    section_counts[key] += 1
            check(len(row['values']), len(table['columns']), where + '/column count', 'shape_checks')
            # Every numeric and null cell must have an independently specified expectation.
            for index, actual in enumerate(row['values']):
                if (actual is None or isinstance(actual, (int, float))) and index not in expected:
                    issues.append(f'{where}/column {index}: unchecked numeric or null cell')
            counts['rows'] += 1

    kpis = data['kpis']
    check(len(kpis), 3, 'KPI count', 'shape_checks')
    expected_kpis = [('PAYEMS', 'Nonfarm payrolls'), ('UNRATE', 'Unemployment rate'), ('CPIAUCNS', 'CPI inflation')]
    for kpi, (sid, label) in zip(kpis, expected_kpis):
        values, end, current = latest(sid)
        expected = (scaled(subtract(current, values.get(month_shift(end, -1))), 1000) if sid == 'PAYEMS'
                    else current if sid == 'UNRATE' else ratio_change(current, values.get(month_shift(end, -12))))
        check(kpi['value'], expected, f'KPI/{sid}/value')
        check(kpi['source'], f'https://fred.stlouisfed.org/series/{sid}', f'KPI/{sid}/source', 'source_checks')
        check(kpi['label'], label, f'KPI/{sid}/label', 'metadata_checks')
        period = date.fromisoformat(end).strftime('%b %Y')
        if period not in kpi['detail']:
            issues.append(f'KPI/{sid}/detail: expected latest period {period}')
        if sid == 'CPIAUCNS' and 'NSA' not in kpi['detail']:
            issues.append('KPI/CPIAUCNS/detail: annual CPI comparison must be labeled NSA')
    return {'counts': dict(counts), 'numeric_by_section': dict(section_counts), 'findings': issues}


def validate_files(data_path, raw_path, catalog_path, config_path):
    return audit(*(json.loads(Path(path).read_text()) for path in [data_path, raw_path, catalog_path, config_path]))


def validate_calculations(root, config_path=None, catalog_path=None):
    """Validate a docs directory (or repository root), failing closed on errors."""
    root = Path(root)
    docs = root if (root / 'data.json').exists() else root / 'docs'
    project = docs.parent
    result = validate_files(docs / 'data.json', docs / 'series.json',
                            catalog_path or project / 'dashboard_catalog.json',
                            config_path or project / 'config.json')
    if result['findings']:
        raise ValueError('Independent calculation validation failed:\n' + '\n'.join(result['findings']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docs-root', type=Path, default=Path(__file__).resolve().parent / 'docs')
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    try:
        result = validate_calculations(args.docs_root, args.config, args.catalog)
    except (KeyError, TypeError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
