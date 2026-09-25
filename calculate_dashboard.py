#!/usr/bin/env python3
"""Build observed economic tables using pandas arithmetic, without projections.

Every business calculation is performed with pandas Series/DataFrame operations.
Missing dates are reindexed to NaN and never interpolated or forward-filled.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import pandas as pd
from economic_labels import apply_economic_labels

ROOT = Path(__file__).resolve().parent
JAN_2021 = pd.Timestamp('2021-01-01')
JAN_2025 = pd.Timestamp('2025-01-01')
WAR_START = '2026-02-28'
CONFIG_GROUPS = ('employment', 'unemployment', 'cpi', 'pce', 'applications', 'claims', 'markets', 'budget', 'participation', 'manufacturing', 'fuels', 'wages', 'extra')


def text(label):
    return {'label': label, 'type': 'text'}


def number(label, digits=1):
    return {'label': label, 'type': 'number', 'digits': digits}


def date_column(label='Period', frequency=None):
    return {'label': label, 'type': 'date', **({'frequency': frequency} if frequency else {})}


def source_for(definition):
    return definition.get('source') or definition.get('sourceUrl') or f"https://fred.stlouisfed.org/series/{definition['id']}"


def frequency(definition):
    return definition.get('frequency', 'monthly').lower()


def canonical_definition(definition, group):
    result = {**definition, 'group': definition.get('group', group), 'frequency': frequency(definition), 'source': source_for(definition)}
    if group in ('employment', 'manufacturing') or definition.get('group') == 'manuf_auto':
        result['multiplier'] = definition.get('multiplier', 1000)
    return result


def dashboard_definitions(config, catalog):
    definitions = {}
    for group in CONFIG_GROUPS:
        for definition in config.get(group, []):
            if not definition.get('id') or (group == 'extra' and definition['id'] == 'UMCSENT'):
                continue
            definitions[definition['id']] = canonical_definition(definition, group)
    for definition in catalog.get('series', []):
        if not definition.get('id') or not definition.get('label'):
            raise ValueError('Catalog series must have id and label')
        merged = {**definitions.get(definition['id'], {}), **definition}
        definitions[definition['id']] = canonical_definition(merged, definition.get('group'))
    return definitions


def observation_series(raw, series_id, cutoff):
    """Validate real, ordered dated observations; do not fill absent values."""
    points = raw.get('observations') if isinstance(raw, dict) else None
    if not isinstance(points, list) or not points:
        raise ValueError(f'Missing observations for {series_id}')
    dates = [point.get('date') for point in points]
    if any(not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) for value in dates):
        raise ValueError(f'Invalid observation date for {series_id}')
    try:
        index = pd.DatetimeIndex(pd.to_datetime(dates, format='%Y-%m-%d', errors='raise'))
    except (ValueError, TypeError) as error:
        raise ValueError(f'Invalid observation date for {series_id}') from error
    if not index.is_unique or not index.is_monotonic_increasing or (index > pd.Timestamp(cutoff).tz_localize(None).normalize()).any():
        raise ValueError(f'Invalid, unordered or future observation for {series_id}')
    values = [point.get('value') for point in points]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise ValueError(f'Invalid numeric observation for {series_id}')
    result = pd.Series(values, index=index, dtype='float64', name=series_id)
    if result.isna().any() or result.isin([float('inf'), -float('inf')]).any():
        raise ValueError(f'Invalid numeric observation for {series_id}')
    return result


def iso_date(value):
    return pd.Timestamp(value).strftime('%Y-%m-%d') if value is not None else None


def latest_date(series):
    return series.index[-1]


def value_at(series, date):
    return series.reindex(pd.DatetimeIndex([date])).iloc[0] if date is not None else float('nan')


def difference(series, start, end):
    """Observed endpoint difference, requiring both exact dates."""
    if end is None or pd.Timestamp(end) < pd.Timestamp(start):
        return float('nan')
    return series.reindex(pd.DatetimeIndex([start, end])).diff().iloc[-1]


def percent_change(series, start, end):
    """Observed percent change; no annualization and no missing-value fill."""
    if end is None or pd.Timestamp(end) < pd.Timestamp(start):
        return float('nan')
    selected = series.reindex(pd.DatetimeIndex([start, end]))
    if selected.isna().any() or selected.iloc[0] <= 0 or selected.iloc[-1] < 0:
        return float('nan')
    return selected.pct_change(fill_method=None).mul(100).iloc[-1]


def growth(series, end, months):
    return percent_change(series, pd.Timestamp(end) - pd.DateOffset(months=months), end)


def average_monthly_change(series, start, end):
    """Arithmetic mean of observed monthly changes over a complete interval."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start.day != 1 or end.day != 1 or start >= end:
        return float('nan')
    values = series.reindex(pd.date_range(start, end, freq='MS'))
    if values.isna().any():
        return float('nan')
    return values.diff().iloc[1:].mean()


def employment_comparison(series, multiplier=1000):
    people = series.mul(multiplier)
    end = latest_date(people)
    return {
        'level': value_at(people, end),
        'monthly': average_monthly_change(people, end - pd.DateOffset(months=1), end),
        'average3': average_monthly_change(people, end - pd.DateOffset(months=3), end),
        'average12': average_monthly_change(people, end - pd.DateOffset(months=12), end),
        'total2021To2025': difference(people, JAN_2021, JAN_2025),
        'average2021To2025': average_monthly_change(people, JAN_2021, JAN_2025),
        'totalSince2025': difference(people, JAN_2025, end),
        'averageSince2025': average_monthly_change(people, JAN_2025, end),
        'totalSince2021': difference(people, JAN_2021, end),
        'monthsSince2025': len(pd.date_range(JAN_2025, end, freq='MS')[1:]) if end >= JAN_2025 else None,
        'period': iso_date(end),
    }


def derive_employment(definition, series, definitions):
    """Align all observed components by date and normalize to people once."""
    components = definition.get('components', [])
    if not components:
        raise ValueError(f"Derived series {definition['id']} has no components")
    inputs, weights = {}, {}
    for part in components:
        component = part if isinstance(part, str) else part['id']
        if component not in series or component not in definitions:
            raise ValueError(f"Missing component {component} for {definition['id']}")
        inputs[component] = series[component].mul(definitions[component].get('multiplier', 1000))
        weights[component] = 1 if isinstance(part, str) else part.get('weight', 1)
    frame = pd.concat(inputs, axis=1, join='inner').dropna(how='any')
    result = frame.mul(pd.Series(weights), axis='columns').sum(axis=1, min_count=len(inputs)).dropna()
    result.name = definition['id']
    if result.empty:
        raise ValueError(f"No common observations for derived series {definition['id']}")
    return result


def observation_at_or_before(series, target, tolerance_days=7):
    """An actual prior observation, without constructing a new observation."""
    target = pd.Timestamp(target)
    eligible = series.loc[series.index <= target]
    if eligible.empty:
        return None
    actual = eligible.index[-1]
    if target - actual > pd.Timedelta(days=tolerance_days):
        return None
    return actual


def prewar_baseline(series, definition, start=WAR_START):
    start = pd.Timestamp(start)
    freq = frequency(definition)
    if freq == 'monthly':
        baseline = start.to_period('M').start_time - pd.DateOffset(months=1)
        return baseline if pd.notna(value_at(series, baseline)) else None
    if freq == 'quarterly':
        baseline = start.to_period('Q').start_time - pd.DateOffset(months=3)
        return baseline if pd.notna(value_at(series, baseline)) else None
    prior_observations = series.loc[series.index < start]
    return observation_at_or_before(prior_observations, start, 14 if freq == 'weekly' else 7)


def price_comparison(series, definition):
    end = latest_date(series)
    freq = frequency(definition)
    if freq == 'weekly':
        prior = end - pd.Timedelta(weeks=1)
        year_ago = end - pd.Timedelta(weeks=52)
    elif freq == 'daily':
        previous = series.loc[series.index < end]
        prior = previous.index[-1] if not previous.empty else None
        year_ago = observation_at_or_before(series, end - pd.DateOffset(months=12))
    else:
        prior, year_ago = end - pd.DateOffset(months=1), end - pd.DateOffset(months=12)
    return {
        'current': value_at(series, end),
        'previous': value_at(series, prior),
        'change': difference(series, prior, end) if prior is not None else float('nan'),
        'yearChange': percent_change(series, year_ago, end) if year_ago is not None else float('nan'),
        'period': iso_date(end),
    }


def json_safe(value):
    """Normalize pandas scalar types and nonfinite missing results to JSON null."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, pd.Timestamp):
        return iso_date(value)
    if hasattr(value, 'item'):
        return json_safe(value.item())
    if isinstance(value, (int, float)):
        return value if pd.notna(value) and value not in (float('inf'), -float('inf')) else None
    raise TypeError(f'Unsupported JSON type: {type(value).__name__}')


def build_dashboard(raw_series, catalog, now, config=None, snapshot_id=None):
    """Create the dashboard schema using only observed values and pandas math."""
    config = config or {}
    if 'series' in raw_series and isinstance(raw_series['series'], dict):
        snapshot_id = snapshot_id or raw_series.get('snapshotId')
        raw_series = raw_series['series']
    retrieved_time = pd.to_datetime(now, utc=True)
    retrieved_at = retrieved_time.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    retrieved = retrieved_time.strftime('%Y-%m-%d')
    definitions = dashboard_definitions(config, catalog)
    series = {series_id: observation_series(raw_series.get(series_id), series_id, retrieved) for series_id in definitions}
    for definition in catalog.get('derived', []):
        series[definition['id']] = derive_employment(definition, series, definitions)
        definitions[definition['id']] = {**definition, 'frequency': 'monthly', 'multiplier': 1, 'units': 'People', 'source': definition.get('source')}
    sections = []

    def add_section(key, label, title, kicker, columns, rows, note, source_note):
        if rows:
            sections.append({'key': key, 'label': label, 'title': title, 'kicker': kicker, 'columns': columns, 'rows': rows, 'note': note, 'sourceNote': source_note})

    def metadata(definition):
        return definitions.get(definition.get('id'), definition)

    def row(definition, values):
        meta = metadata(definition)
        components = [part if isinstance(part, str) else part['id'] for part in meta.get('components', [])]
        sources = [{'label': definitions.get(component, {}).get('label', component), 'url': source_for(definitions.get(component, {'id': component}))} for component in components]
        result = {'id': definition.get('id'), 'values': values, 'source': meta.get('source') or (source_for(meta) if definition.get('id') and not components else None), 'sa': meta.get('sa'), 'frequency': frequency(meta)}
        if sources:
            result['sources'] = sources
        if meta.get('note'):
            result['note'] = meta['note']
        return result

    def unique(items):
        return list({item['id']: metadata(item) for item in items if item.get('id')}.values())

    def group(name):
        return [definition for definition in definitions.values() if definition.get('group') == name]

    employment_columns = [text('Industry'), number('Total jobs', 0), number('Monthly change', 0), number('3-month avg.', 0), number('12-month avg.', 0), number('Jan 2021–Jan 2025 total', 0), number('Jan 2021–Jan 2025 monthly avg.', 0), number('Since Jan 2025 total', 0), number('Since Jan 2025 monthly avg.', 0), number('Since Jan 2021 total', 0), text('Adjustment'), date_column('Period', 'monthly')]

    def employment_rows(items, include_level=True):
        result = []
        for definition in items:
            stats = employment_comparison(series[definition['id']], metadata(definition).get('multiplier', 1000))
            result.append(row(definition, [definition['label'], stats['level'], stats['monthly'], stats['average3'], stats['average12'], stats['total2021To2025'], stats['average2021To2025'], stats['totalSince2025'], stats['averageSince2025'], stats['totalSince2021'], metadata(definition).get('sa', 'SA'), stats['period']]))
        if not include_level:
            for item in result:
                item['values'] = item['values'][:1] + item['values'][2:]
        return result

    employment_note = 'Levels and changes are people. Jan 2021–Jan 2025 uses exact January levels and 48 observed monthly changes. Since Jan 2025 uses the exact January 2025 level and observed monthly changes to the row’s latest month. Totals require both endpoints; averages require every intervening month. Subsets overlap and should not be added to parent industries.'
    add_section('employment', 'Employment', 'Employment by industry', 'LABOR MARKET', employment_columns[:1] + employment_columns[2:], employment_rows(unique(config.get('employment', [])), include_level=False), employment_note.replace('Levels and changes', 'Changes'), 'BLS establishment survey via FRED. Published seasonal adjustment is retained. Pandas converts raw thousands of people to people; monthly averages are means of observed monthly differences.')

    def rate_rows(items):
        result = []
        for definition in items:
            observed = series[definition['id']]
            end = latest_date(observed)
            result.append(row(definition, [definition['label'], value_at(observed, end), difference(observed, end - pd.DateOffset(months=1), end), difference(observed, end - pd.DateOffset(months=12), end), iso_date(end)]))
        return result

    def rate_columns(label):
        return [text(label), number('Rate (%)'), number('1m change (pp)'), number('1y change (pp)'), date_column('Period', 'monthly')]

    add_section('unemployment', 'Unemployment', 'Unemployment by race and demographic', 'LABOR MARKET', rate_columns('Population'), rate_rows(config.get('unemployment', [])), 'Seasonally adjusted. Ages 16 and over unless otherwise noted. Hispanic or Latino ethnicity may be of any race; these groups overlap.', 'BLS household survey via FRED. pp means percentage points. Observed differences are computed with pandas.')

    inflation_rows = []
    inflation_comparisons = catalog.get('inflationComparisons', {})
    for name in ('cpi', 'pce'):
        for definition in config.get(name, []):
            if not definition.get('id'):
                continue
            observed = series[definition['id']]
            end = latest_date(observed)
            yearly_id = inflation_comparisons.get(definition['id'], definition['id'])
            yearly = series[yearly_id]
            record = row(definition, [f"{name.upper()} · {definition['label']}", growth(observed, end, 1), growth(yearly, end, 12), iso_date(end), definitions[yearly_id]['sa']])
            if yearly_id != definition['id']:
                record['sources'] = [{'label': 'Monthly: SA', 'url': source_for(definitions[definition['id']])}, {'label': '12-month: NSA', 'url': source_for(definitions[yearly_id])}]
            inflation_rows.append(record)
    add_section('inflation', 'CPI & PCE inflation', 'CPI and PCE inflation', 'PRICES', [text('Measure / component'), number('1-month change (%, SA)'), number('12-month change (%)'), date_column('Latest month', 'monthly'), text('12-month adjustment')], inflation_rows, 'Monthly changes use seasonally adjusted indexes. CPI 12-month changes use unadjusted indexes, matching BLS reporting; PCE 12-month changes use seasonally adjusted indexes. Core excludes food and energy. These are observed changes, not annualized rates.', 'BLS CPI and BEA PCE via FRED. Separate SA and NSA source links identify the CPI inputs. Both comparisons end in the displayed month; missing exact observations remain unavailable.')

    price_rows = []
    for definition in unique([*config.get('fuels', []), *group('prices')]):
        prices = price_comparison(series[definition['id']], definition)
        price_rows.append(row(definition, [definition['label'], prices['current'], prices['change'], prices['yearChange'], definition.get('units'), frequency(definition), definition.get('sa'), prices['period']]))
    add_section('prices', 'Gas & basic goods', 'Gas prices and everyday goods', 'COST OF LIVING', [text('Item'), number('Latest price ($)', 3), number('Change from prior period ($)', 3), number('YoY (%)'), text('Unit'), text('Frequency'), text('Adjustment'), date_column()], price_rows, 'Actual dollar prices per stated unit. These series retain their published seasonal adjustment; most average retail prices are NSA. They are national averages, not a local shopping quote. The prior period is one month for monthly prices or one week for weekly fuel prices.', 'BLS average retail prices and EIA fuel prices via FRED. Weekly YoY compares 52 weeks earlier; monthly YoY compares the same month a year earlier. Pandas uses exact observations; missing periods remain unavailable.')

    auto_definitions = unique([*[definition for definition in config.get('employment', []) if definition['id'] == 'MANEMP'], *config.get('manufacturing', []), *group('manuf_auto'), *[definition for definition in catalog.get('derived', []) if definition.get('group') == 'manuf_auto']])
    add_section('manufacturing', 'Manufacturing & autos', 'Manufacturing, auto manufacturing and dealers', 'JOBS BY INDUSTRY & STATE', employment_columns, employment_rows(auto_definitions), f'{employment_note} “Total auto jobs” means motor vehicles and parts manufacturing plus motor vehicle and parts dealers; it does not cover every auto-related business.', 'BLS establishment-survey data via FRED, using published seasonal adjustment. Pandas aligns derived components on dates present in every source before summing. The selected states are Michigan, Ohio, Wisconsin, Pennsylvania and Minnesota, not a complete geographic region.')

    us_gdp_rows = []
    for definition in group('gdp_us'):
        observed = series[definition['id']]
        end = latest_date(observed)
        us_gdp_rows.append(row(definition, [definition['label'], value_at(observed, end), value_at(observed, end - pd.DateOffset(months=3)), value_at(observed, end - pd.DateOffset(months=12)), f"{definition['units']} · {definition['sa']}", iso_date(end)]))
    if us_gdp_rows and 'GDPC1' in series:
        observed = series['GDPC1']
        end = latest_date(observed)
        definition = definitions['GDPC1']
        record = row(definition, ['Real GDP level', value_at(observed, end), value_at(observed, end - pd.DateOffset(months=3)), value_at(observed, end - pd.DateOffset(months=12)), f"{definition['units']} · {definition['sa']}", iso_date(end)])
        record['digits'] = {'1': 3, '2': 3, '3': 3}
        us_gdp_rows.append(record)
    add_section('gdp_us', 'U.S. real GDP', 'U.S. real GDP: official BEA figures', 'ECONOMIC OUTPUT', [text('Measure'), number('Latest'), number('Previous quarter'), number('Same quarter a year earlier'), text('Unit / convention'), date_column('Quarter', 'quarterly')], us_gdp_rows, 'Growth is the BEA-published percent change from the preceding quarter at a seasonally adjusted annual rate (SAAR). Each growth entry describes its own quarter; it is not a 4-quarter change or a forecast. The GDP level is inflation-adjusted output in billions of chained 2017 dollars at an annual rate.', 'BEA NIPA Tables 1.1.1 and 1.1.6 via FRED. Values are read directly from the published series. For growth during a single quarter and cumulative comparisons, use G7 real GDP.')

    gdp_rows = []
    gdp_definitions = group('gdp')
    if gdp_definitions:
        common_gdp = pd.concat({item['id']: series[item['id']] for item in gdp_definitions}, axis=1, join='inner').dropna(how='any')
        if common_gdp.empty:
            raise ValueError('No common observation quarter for G7 GDP comparison')
        gdp_comparison_quarter = common_gdp.index[-1]
    for definition in gdp_definitions:
        observed = series[definition['id']]
        end = gdp_comparison_quarter
        gdp_rows.append(row(definition, [definition['label'], growth(observed, end, 3), growth(observed, end, 12), percent_change(observed, JAN_2021, JAN_2025), percent_change(observed, JAN_2025, end), percent_change(observed, JAN_2021, end), iso_date(end)]))
    add_section('gdp', 'G7 real GDP', 'G7 real GDP growth and cumulative changes', 'ECONOMIC OUTPUT', [text('Economy'), number('Quarterly change (%, not annualized)'), number('4-quarter change (%)'), number('Q1 2021–Q1 2025 cumulative change (%)'), number('Since Q1 2025 cumulative change (%)'), number('Since Q1 2021 cumulative change (%)'), date_column('Comparison quarter', 'quarterly')], gdp_rows, 'All countries use the latest quarter available for every country, with seasonally adjusted real GDP. Quarterly change is growth during one quarter, not an annual rate. The 4-quarter column compares with the same quarter a year earlier, not annual-average GDP. Cumulative columns compare levels at the stated endpoints and are not average annual growth rates.', 'BEA and national statistical sources via FRED. Pandas calculates percentage changes from each country’s real GDP series; national-currency levels are omitted from this comparison. Q1 baselines are full quarters, not January-only observations or exact presidential-term boundaries. The common comparison quarter avoids mixing periods when national release dates differ; the U.S. tab separately reports the latest BEA quarter.')

    application_rows = []
    for definition in config.get('applications', []):
        observed = series[definition['id']]
        end = latest_date(observed)
        application_rows.append(row(definition, [definition['label'], value_at(observed, end), growth(observed, end, 1), growth(observed, end, 12), iso_date(end)]))
    add_section('applications', 'Business applications', 'Business applications', 'BUSINESS ACTIVITY', [text('Applications'), number('Level', 0), number('MoM (%)'), number('YoY (%)'), date_column('Period', 'monthly')], application_rows, 'Monthly applications, seasonally adjusted. High-propensity applications are a subset of total applications, not additional business formations.', 'U.S. Census Bureau via FRED. Changes are computed with pandas from observed application counts.')

    claims_rows = []
    for definition in config.get('claims', []):
        observed = series[definition['id']]
        end = latest_date(observed)
        claims_rows.append(row(definition, [definition['label'], value_at(observed, end), value_at(observed, end - pd.Timedelta(weeks=1)), value_at(observed, end - pd.Timedelta(weeks=52)), iso_date(end)]))
    add_section('claims', 'Jobless claims', 'Initial and continued claims', 'LABOR MARKET', [text('Measure'), number('Claims', 0), number('1 week ago', 0), number('52 weeks ago', 0), date_column('Week ending')], claims_rows, 'Seasonally adjusted. Continued claims generally refer to an earlier week than initial claims.', 'U.S. Employment and Training Administration via FRED. Comparisons require exact dates; missing observations remain unavailable.')

    market_rows = []
    for definition in config.get('markets', []):
        observed = series[definition['id']]
        end = latest_date(observed)
        targets = [end - pd.DateOffset(months=1), pd.Timestamp(year=end.year, month=1, day=1) - pd.Timedelta(days=1), end - pd.DateOffset(months=12)]
        changes = []
        for target in targets:
            baseline = observation_at_or_before(observed, target)
            changes.append(percent_change(observed, baseline, end) if baseline is not None else float('nan'))
        market_rows.append(row(definition, [definition['label'], value_at(observed, end), *changes, iso_date(end)]))
    add_section('markets', 'Stock market', 'Stock market indexes', 'FINANCIAL MARKETS', [text('Index'), number('Close'), number('1m (%)'), number('YTD (%)'), number('1y (%)'), date_column('Close date')], market_rows, 'Daily closing price indexes, not live prices. Changes exclude dividends. Market series are not seasonally adjusted.', 'S&P Dow Jones Indices and Nasdaq via FRED. Calendar lookbacks use a prior observed close within seven days. Pandas computes returns from those observed prices.')

    budget_rows = []
    monthly_budget = next((definition for definition in config.get('budget', []) if definition['id'] == 'MTSDS133FMS'), None)
    if monthly_budget:
        observed = series[monthly_budget['id']]
        end = latest_date(observed)
        deficits = observed.mul(-0.001)
        fiscal_start = pd.Timestamp(year=end.year, month=10, day=1)
        if fiscal_start > end:
            fiscal_start = fiscal_start - pd.DateOffset(years=1)

        def observed_sum(start):
            required = pd.date_range(start, end, freq='MS')
            return deficits.reindex(required).sum(min_count=len(required))

        trailing_start = end - pd.DateOffset(months=11)
        for label, value, start in [('Monthly deficit', value_at(deficits, end), end), ('Fiscal year to date deficit', observed_sum(fiscal_start), fiscal_start), ('Trailing 12 months deficit', observed_sum(trailing_start), trailing_start)]:
            period = end.strftime('%b %Y') if start == end else f"{start.strftime('%b %Y')}–{end.strftime('%b %Y')}"
            budget_rows.append(row(monthly_budget, [label, value, 'USD billions', period]))
    annual_budget = next((definition for definition in config.get('budget', []) if definition['id'] == 'FYFSGDA188S'), None)
    if annual_budget:
        observed = series[annual_budget['id']].mul(-1)
        end = latest_date(observed)
        budget_rows.append(row(annual_budget, ['Fiscal year deficit / GDP', value_at(observed, end), '% of GDP', f'FY {end.year}']))
    add_section('budget', 'Federal budget', 'Federal deficit measures', 'FISCAL POSITION', [text('Measure'), number('Deficit'), text('Units'), text('Period ending')], budget_rows, 'Positive values indicate a deficit; negative values indicate a surplus. Fiscal year to date begins in October. Published budget balances are NSA.', 'Treasury and OMB via FRED. Pandas sums observed monthly balances only when every required month is available.')

    add_section('participation', 'Participation', 'Prime-age participation and employment', 'LABOR MARKET', rate_columns('Measure'), rate_rows(config.get('participation', [])), 'People ages 25–54. Seasonally adjusted. Participation includes employed people and unemployed people seeking work.', 'BLS household survey via FRED. pp means percentage points. Differences are computed with pandas.')
    context_rows = []
    for definition in [*[definition for definition in config.get('extra', []) if definition['id'] != 'UMCSENT'], *config.get('wages', [])]:
        observed = series[definition['id']]
        end = latest_date(observed)
        context_rows.append(row(definition, [definition['label'], value_at(observed, end), definition.get('units'), iso_date(end)]))
    add_section('context', 'Labor context', 'Job openings, quits, underemployment and wages', 'LABOR MARKET', [text('Measure'), number('Value', 2), text('Units'), date_column('Period', 'monthly')], context_rows, 'Published seasonal adjustment is retained. Job openings and quits come from JOLTS; U-6 is a broader measure of labor underutilization. Wages are nominal dollars per hour.', 'BLS via FRED. Observation months differ across releases.')

    default_war = ['GASREGW', 'GASDESW', 'DCOILWTICO', 'DCOILBRENTEU', 'SP500', 'DJIA', 'NASDAQCOM']
    war_ids = [item if isinstance(item, str) else item['id'] for item in [*catalog.get('war', default_war), 'CPIAUCSL', 'CPILFESL', 'PCEPI', 'PCEPILFE', 'PAYEMS', 'UNRATE', 'ICSA']]
    war_rows = []
    war_labels = {'CPIAUCSL': 'CPI price index', 'CPILFESL': 'Core CPI price index', 'PCEPI': 'PCE price index', 'PCEPILFE': 'Core PCE price index', 'PAYEMS': 'Total nonfarm payroll jobs', 'UNRATE': 'Unemployment rate (U-3)', 'ICSA': 'Initial jobless claims'}
    for definition in unique([definitions[series_id] for series_id in war_ids if series_id in definitions]):
        observed = series[definition['id']].mul(definition.get('multiplier', 1))
        end = latest_date(observed)
        baseline = prewar_baseline(observed, definition)
        unit = 'Jobs' if definition['id'] == 'PAYEMS' else definition.get('units') or ('Percent' if definition['id'] == 'UNRATE' else '')
        record = row(definition, [war_labels.get(definition['id'], definition['label']), value_at(observed, baseline), iso_date(baseline), value_at(observed, end), iso_date(end), difference(observed, baseline, end) if baseline is not None else float('nan'), percent_change(observed, baseline, end) if baseline is not None else float('nan'), f"{unit} · {definition.get('sa', 'SA')}"])
        change_unit = 'Percentage points' if unit.lower() in ('percent', '%') else 'Index points' if unit.lower().startswith('index') else 'Claims' if definition['id'] == 'ICSA' else unit
        record['values'].append(change_unit)
        if unit.lower() in ('people', 'persons', 'number', 'jobs'):
            display_digits = 0
        elif unit.lower() in ('percent', '%'):
            display_digits = 1
        elif 'barrel' in unit.lower() or frequency(definition) == 'daily':
            display_digits = 2
        else:
            display_digits = 3
        record['digits'] = {'1': display_digits, '3': display_digits, '5': display_digits}
        war_rows.append(record)
    add_section('war', 'Since Iran War began', 'Changes since February 28, 2026', 'BEFORE & AFTER', [text('Indicator'), number('Baseline value', 3), date_column('Baseline observation'), number('Latest value', 3), date_column('Latest observation'), number('Absolute change', 3), number('Change (%)'), text('Unit / adjustment'), text('Change unit')], war_rows, 'User-selected start: February 28, 2026. Daily and weekly baselines are the last available observation before that date; monthly baselines use January 2026 because February spans the start of the war. Each baseline is shown explicitly. These comparisons describe changes over time and do not attribute them to the war.', 'Sources via FRED. Pandas uses observed baselines within 7 days for daily data and 14 days for weekly data; missing monthly baselines remain unavailable. Rate differences under absolute change are percentage points; percent change is relative to the baseline.')

    kpis = []
    if 'PAYEMS' in series:
        observed = series['PAYEMS'].mul(definitions['PAYEMS'].get('multiplier', 1000))
        end = latest_date(observed)
        value = average_monthly_change(observed, end - pd.DateOffset(months=1), end)
        kpis.append({'label': 'Nonfarm payrolls', 'value': value, 'digits': 0, 'prefix': '+' if pd.notna(value) and value >= 0 else '', 'suffix': '', 'detail': f"Monthly job change · {end.strftime('%b %Y')} · SA", 'source': source_for(definitions['PAYEMS'])})
    if 'UNRATE' in series:
        observed = series['UNRATE']
        end = latest_date(observed)
        kpis.append({'label': 'Unemployment rate', 'value': value_at(observed, end), 'digits': 1, 'prefix': '', 'suffix': '%', 'detail': f"Overall U-3 · {end.strftime('%b %Y')} · SA", 'source': source_for(definitions['UNRATE'])})
    if 'CPIAUCSL' in series:
        cpi_headline_id = inflation_comparisons.get('CPIAUCSL', 'CPIAUCSL')
        observed = series[cpi_headline_id]
        end = latest_date(observed)
        kpis.append({'label': 'CPI inflation', 'value': growth(observed, end, 12), 'digits': 1, 'prefix': '', 'suffix': '%', 'detail': f"12-month change · {end.strftime('%b %Y')} · {definitions[cpi_headline_id]['sa']}", 'source': source_for(definitions[cpi_headline_id])})
    apply_economic_labels(sections)
    notes = {**catalog.get('notes', {}), 'calculations': 'All dashboard arithmetic uses pandas on observed values. Missing observations are not estimated, interpolated or filled.', 'gdp': 'Real GDP comparisons use observed quarterly levels. National currency levels are not directly comparable. Q1 baselines are full quarters, not January alone.'}
    result = {'retrieved': retrieved, 'retrievedAt': retrieved_at, 'warStart': WAR_START, 'kpis': kpis, 'sections': sections, 'notes': notes, 'calculationEngine': f'pandas {pd.__version__}'}
    if snapshot_id:
        result['snapshotId'] = snapshot_id
    return json_safe(result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--series', type=Path, default=ROOT / 'docs/series.json')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--catalog', type=Path, default=ROOT / 'dashboard_catalog.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/data.json')
    args = parser.parse_args(argv)
    raw = json.loads(args.series.read_text())
    if not raw.get('retrievedAt') or not raw.get('snapshotId'):
        raise ValueError('Raw series export requires retrievedAt and snapshotId; no fresh date is invented for cached data')
    result = build_dashboard(raw, json.loads(args.catalog.read_text()), raw['retrievedAt'], json.loads(args.config.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=args.output.parent, prefix=f'.{args.output.name}.', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
        os.replace(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Calculated {len(result['sections'])} tables with pandas from observations retrieved {result['retrievedAt']}.")


if __name__ == '__main__':
    main()
