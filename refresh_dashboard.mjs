#!/usr/bin/env node
/** Refresh the public dashboard directly from FRED. Node.js 20+, no API key. */
import { readFile, mkdir, writeFile, rename, unlink } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { randomUUID } from 'node:crypto';
import { fetchFredSeries, valueAt, latestDate, monthShift, growth, averageJobChange } from './data.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const JAN_2021 = '2021-01-01';
const JAN_2025 = '2025-01-01';
export const WAR_START = '2026-02-28';
const CONFIG_GROUPS = ['employment', 'unemployment', 'cpi', 'pce', 'applications', 'claims', 'markets', 'budget', 'participation', 'manufacturing', 'fuels', 'wages', 'extra'];
const text = label => ({ label, type: 'text' });
const number = (label, digits = 1) => ({ label, type: 'number', digits });
const date = (label = 'Period', frequency) => ({ label, type: 'date', ...(frequency ? { frequency } : {}) });
const dayShift = (d, days) => new Date(Date.parse(`${d}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
const finite = value => typeof value === 'number' && Number.isFinite(value);
const scaled = (value, multiplier) => finite(value) ? value * multiplier : null;
const subtract = (a, b) => finite(a) && finite(b) ? a - b : null;
const percent = (a, b) => finite(a) && finite(b) && a >= 0 && b > 0 ? (a / b - 1) * 100 : null;
const monthLabel = d => d ? new Date(`${d}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' }) : 'Unavailable';
const sourceFor = def => def.source ?? def.sourceUrl ?? `https://fred.stlouisfed.org/series/${def.id}`;
const frequency = def => (def.frequency ?? 'monthly').toLowerCase();
const getSeries = (series, id) => series instanceof Map ? series.get(id) : series[id];
const observations = s => s?.observations ?? [];

/** Jan-to-Jan intervals count elapsed months, not the number of observations. */
export function elapsedMonths(start, end) {
  if (!/^\d{4}-\d{2}-01$/.test(start ?? '') || !/^\d{4}-\d{2}-01$/.test(end ?? '')) return null;
  const months = (Number(end.slice(0, 4)) - Number(start.slice(0, 4))) * 12 + Number(end.slice(5, 7)) - Number(start.slice(5, 7));
  return months >= 0 ? months : null;
}

export function employmentComparison(s, end = latestDate(s), multiplier = 1000) {
  const value = d => d ? valueAt(s, d) : null;
  const delta = (start, finish) => finish && finish >= start ? scaled(subtract(value(finish), value(start)), multiplier) : null;
  const currentMonths = elapsedMonths(JAN_2025, end);
  return {
    level: scaled(value(end), multiplier),
    monthly: end ? averageJobChange(s, end, 1, multiplier) : null,
    average3: end ? averageJobChange(s, end, 3, multiplier) : null,
    average12: end ? averageJobChange(s, end, 12, multiplier) : null,
    total2021To2025: delta(JAN_2021, JAN_2025),
    average2021To2025: averageJobChange(s, JAN_2025, 48, multiplier),
    totalSince2025: delta(JAN_2025, end),
    averageSince2025: currentMonths > 0 ? averageJobChange(s, end, currentMonths, multiplier) : null,
    totalSince2021: delta(JAN_2021, end),
    monthsSince2025: currentMonths,
    period: end,
  };
}

/** Components are converted to people before adding and require the same actual date. */
export function deriveEmployment(def, series, definitions) {
  const parts = def.components.map(id => ({ id: typeof id === 'string' ? id : id.id, weight: typeof id === 'string' ? 1 : (id.weight ?? 1) }));
  if (!parts.length) throw new Error(`Derived series ${def.id} has no components`);
  const inputs = parts.map(part => {
    const s = getSeries(series, part.id), metadata = definitions.get(part.id);
    if (!s || !metadata) throw new Error(`Missing component ${part.id} for ${def.id}`);
    return { ...part, s, multiplier: metadata.multiplier ?? 1000, values: new Map(s.observations.map(p => [p.date, p.value])) };
  });
  const values = inputs[0].s.observations.filter(p => inputs.every(item => finite(item.values.get(p.date)))).map(p => ({
    date: p.date,
    value: inputs.reduce((sum, item) => sum + item.values.get(p.date) * item.multiplier * item.weight, 0),
  }));
  if (!values.length) throw new Error(`No common observations for derived series ${def.id}`);
  return { id: def.id, observations: values, fetchedAt: inputs.map(item => item.s.fetchedAt).filter(Boolean).sort().at(-1) ?? null, derived: true, components: parts.map(p => p.id), units: 'People', multiplier: 1 };
}

/** Daily market lookbacks use a prior trading day within seven calendar days. */
export function observationAtOrBefore(s, target, toleranceDays = 7) {
  const point = observations(s).filter(p => p.date <= target).sort((a, b) => a.date.localeCompare(b.date)).at(-1);
  return point && (Date.parse(target) - Date.parse(point.date)) / 86400000 <= toleranceDays ? point : null;
}

/** A monthly February value spans the war; January is the exact prewar monthly baseline. */
export function prewarBaseline(s, definition, start = WAR_START) {
  const freq = frequency(definition);
  if (freq === 'monthly') {
    const baseline = monthShift(`${start.slice(0, 7)}-01`, -1);
    const value = valueAt(s, baseline);
    return finite(value) ? { date: baseline, value } : null;
  }
  if (freq === 'quarterly') {
    const month = Number(start.slice(5, 7));
    const quarterStart = `${start.slice(0, 4)}-${String(1 + Math.floor((month - 1) / 3) * 3).padStart(2, '0')}-01`;
    const baseline = monthShift(quarterStart, -3);
    const value = valueAt(s, baseline);
    return finite(value) ? { date: baseline, value } : null;
  }
  return observationAtOrBefore(s, dayShift(start, -1), freq === 'weekly' ? 14 : 7);
}

export function priceComparison(s, def) {
  const d = latestDate(s), current = d ? valueAt(s, d) : null;
  const freq = frequency(def);
  const priorDate = d ? (freq === 'weekly' ? dayShift(d, -7) : freq === 'daily' ? observations(s).filter(p => p.date < d).at(-1)?.date : monthShift(d, -1)) : null;
  const previous = priorDate ? valueAt(s, priorDate) : null;
  const yearDate = d ? (freq === 'weekly' ? dayShift(d, -364) : monthShift(d, -12)) : null;
  const yearAgo = yearDate ? (freq === 'daily' ? observationAtOrBefore(s, yearDate)?.value : valueAt(s, yearDate)) : null;
  return { current, previous, change: subtract(current, previous), yearChange: percent(current, yearAgo), period: d };
}

function canonicalDefinition(def, group) {
  return { ...def, group: def.group ?? group, frequency: frequency(def), source: sourceFor(def), ...(group === 'employment' || group === 'manufacturing' || def.group === 'manuf_auto' ? { multiplier: def.multiplier ?? 1000 } : {}) };
}

export function dashboardDefinitions(config, catalog) {
  const definitions = new Map();
  for (const group of CONFIG_GROUPS) for (const def of config[group] ?? []) {
    if (!def.id || (group === 'extra' && def.id === 'UMCSENT')) continue;
    definitions.set(def.id, canonicalDefinition(def, group));
  }
  for (const def of catalog.series ?? []) {
    if (!def.id || !def.label) throw new Error('Catalog series must have id and label');
    const old = definitions.get(def.id) ?? {};
    definitions.set(def.id, canonicalDefinition({ ...old, ...def }, def.group));
  }
  return definitions;
}

function validateInput(s, id, cutoff) {
  if (!s || !Array.isArray(s.observations) || !s.observations.length) throw new Error(`Missing observations for ${id}`);
  let previous = '';
  for (const point of s.observations) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(point.date) || !Number.isFinite(Date.parse(point.date)) || new Date(`${point.date}T00:00:00Z`).toISOString().slice(0, 10) !== point.date || !finite(point.value) || point.date <= previous || point.date > cutoff) {
      throw new Error(`Invalid, unordered or future observation for ${id}: ${point.date}`);
    }
    previous = point.date;
  }
}

/** Pure table builder. Missing historical observations stay null; inputs are not modified. */
export function buildDashboard(inputSeries, catalog, now, config = {}) {
  const retrievedAt = new Date(now).toISOString(), retrieved = retrievedAt.slice(0, 10);
  const definitions = dashboardDefinitions(config, catalog);
  const series = new Map();
  for (const [id] of definitions) {
    const s = getSeries(inputSeries, id);
    validateInput(s, id, retrieved);
    series.set(id, s);
  }
  for (const def of catalog.derived ?? []) {
    const s = deriveEmployment(def, series, definitions);
    series.set(def.id, s);
    definitions.set(def.id, { ...def, frequency: 'monthly', multiplier: 1, units: 'People', source: def.source ?? null });
  }
  const sections = [];
  const addSection = (key, label, title, kicker, columns, rows, note, sourceNote) => {
    if (rows.length) sections.push({ key, label, title, kicker, columns, rows, note, sourceNote });
  };
  const definition = def => definitions.get(def.id) ?? def;
  const row = (def, values) => {
    const meta = definition(def);
    const components = (meta.components ?? []).map(part => typeof part === 'string' ? part : part.id);
    const sources = components.map(id => ({ label: definitions.get(id)?.label ?? id, url: sourceFor(definitions.get(id) ?? { id }) }));
    return { id: def.id ?? null, values, source: meta.source ?? (def.id && !components.length ? sourceFor(meta) : null), ...(sources.length ? { sources } : {}), sa: meta.sa ?? null, frequency: frequency(meta), ...(meta.note ? { note: meta.note } : {}) };
  };
  const unique = items => [...new Map(items.filter(def => def.id).map(def => [def.id, definition(def)])).values()];
  const group = name => [...definitions.values()].filter(def => def.group === name);
  const employmentColumns = [text('Industry'), number('Total jobs', 0), number('Monthly change', 0), number('3-month avg.', 0), number('12-month avg.', 0), number('Jan 2021–Jan 2025 total', 0), number('Jan 2021–Jan 2025 monthly avg.', 0), number('Since Jan 2025 total', 0), number('Since Jan 2025 monthly avg.', 0), number('Since Jan 2021 total', 0), text('Adjustment'), date('Period', 'monthly')];
  const employmentRows = items => items.map(def => {
    const stats = employmentComparison(series.get(def.id), undefined, definition(def).multiplier ?? 1000);
    return row(def, [def.label, stats.level, stats.monthly, stats.average3, stats.average12, stats.total2021To2025, stats.average2021To2025, stats.totalSince2025, stats.averageSince2025, stats.totalSince2021, definition(def).sa ?? 'SA', stats.period]);
  });
  const employmentNote = 'Levels and changes are people. Jan 2021–Jan 2025 uses exact January levels and 48 elapsed monthly changes. Since Jan 2025 uses the exact January 2025 level and elapsed months to the row’s latest month. Totals require both endpoints; monthly averages also require every intervening month. Subsets overlap and should not be added to parent industries.';
  addSection('employment', 'Employment', 'Employment by industry', 'LABOR MARKET', employmentColumns, employmentRows(unique(config.employment ?? [])), employmentNote, 'BLS establishment survey, retrieved through FRED. Published seasonal adjustment is retained. Raw FRED employment levels are thousands of people; displayed values are multiplied by 1,000.');

  const rateRows = items => items.map(def => {
    const s = series.get(def.id), d = latestDate(s), v = valueAt(s, d);
    return row(def, [def.label, v, subtract(v, valueAt(s, monthShift(d, -1))), subtract(v, valueAt(s, monthShift(d, -12))), d]);
  });
  const rateColumns = name => [text(name), number('Rate (%)'), number('1m change (pp)'), number('1y change (pp)'), date('Period', 'monthly')];
  addSection('unemployment', 'Unemployment', 'Unemployment by race and demographic', 'LABOR MARKET', rateColumns('Population'), rateRows(config.unemployment ?? []), 'Seasonally adjusted. Ages 16 and over unless otherwise noted. Hispanic or Latino ethnicity may be of any race; these groups overlap.', 'BLS household survey via FRED. pp means percentage points.');

  const inflationRows = ['cpi', 'pce'].flatMap(name => (config[name] ?? []).map(def => {
    const label = `${name.toUpperCase()} · ${def.label}`;
    if (!def.id) return { id: null, values: [label, null, null, null, null], source: null, note: 'Exact monthly series is not configured; no automated value is published.' };
    const s = series.get(def.id), d = latestDate(s);
    return row(def, [label, growth(s, d, 1), growth(s, d, 3, true), growth(s, d, 12), d]);
  }));
  addSection('inflation', 'CPI & PCE inflation', 'CPI and PCE inflation', 'PRICES', [text('Measure / component'), number('MoM (%)'), number('3m annualized (%)'), number('YoY (%)'), date('Period', 'monthly')], inflationRows, 'Changes calculated from published seasonally adjusted price indexes. CPI and PCE have different coverage and weights. PCE core goods, core services and housing remain unavailable until exact monthly sources are configured.', 'BLS CPI and BEA PCE via FRED. SA CPI index-based YoY can differ slightly from the headline NSA convention. Annualization compounds index ratios.');

  const priceDefs = unique([...(config.fuels ?? []), ...group('prices')]);
  addSection('prices', 'Gas & basic goods', 'Gas prices and everyday goods', 'COST OF LIVING', [text('Item'), number('Latest price ($)', 3), number('Change from prior period ($)', 3), number('YoY (%)'), text('Unit'), text('Frequency'), text('Adjustment'), date()], priceDefs.map(def => {
    const p = priceComparison(series.get(def.id), def);
    return row(def, [def.label, p.current, p.change, p.yearChange, def.units, frequency(def), def.sa, p.period]);
  }), 'Actual dollar prices per stated unit. These series retain their published seasonal adjustment; most average retail prices are NSA. They are national averages, not a local shopping quote. The prior period is one month for monthly prices or one week for weekly fuel prices.', 'BLS average retail prices and EIA fuel prices via FRED. Weekly YoY compares 52 weeks earlier; monthly YoY compares the same month a year earlier. Missing periods are never filled forward.');

  const autoDefs = unique([...(config.employment ?? []).filter(def => def.id === 'MANEMP'), ...(config.manufacturing ?? []), ...group('manuf_auto'), ...(catalog.derived ?? []).filter(def => def.group === 'manuf_auto')]);
  const unavailable = (catalog.unavailable ?? []).filter(def => ['manuf_auto', 'manufacturing'].includes(def.group));
  const autoRows = employmentRows(autoDefs);
  for (const def of unavailable) autoRows.push({ id: null, source: def.source ?? null, values: [def.label, ...Array(9).fill(null), def.sa ?? 'Unavailable', null], note: def.note ?? def.reason ?? 'A matching public series is not configured.' });
  addSection('manufacturing', 'Manufacturing & autos', 'Manufacturing, auto manufacturing and dealers', 'JOBS BY INDUSTRY & STATE', employmentColumns, autoRows, `${employmentNote} “Total auto jobs” means motor vehicles and parts manufacturing plus motor vehicle and parts dealers; it does not cover every auto-related business. State components are labeled explicitly.`, ['BLS establishment-survey data via FRED, seasonally adjusted. Derived totals use only dates common to all components. The selected states are Michigan, Ohio, Wisconsin, Pennsylvania and Minnesota, not a complete geographic region.', ...(unavailable.map(def => `${def.label}: ${def.note ?? def.reason ?? 'Unavailable.'}`))].join(' '));

  const gdpDefs = group('gdp');
  addSection('gdp', 'Real GDP', 'Real GDP: U.S. and G7', 'ECONOMIC OUTPUT', [text('Economy'), number('Real GDP level', 2), text('Published unit'), number('QoQ annualized (%)'), number('YoY (%)'), number('Q1 2021–Q1 2025 change (%)'), number('Since Q1 2025 change (%)'), number('Since Q1 2021 change (%)'), text('Adjustment'), date('Quarter', 'quarterly')], gdpDefs.map(def => {
    const s = series.get(def.id), d = latestDate(s), v = valueAt(s, d);
    return row(def, [def.label, v, def.units, growth(s, d, 3, true), growth(s, d, 12), percent(valueAt(s, JAN_2025), valueAt(s, JAN_2021)), percent(v, valueAt(s, JAN_2025)), percent(v, valueAt(s, JAN_2021)), def.sa, d]);
  }), 'Inflation-adjusted output. Compare growth rates across countries: published levels use different currencies, reference years and annualization conventions. January baselines represent Q1, not monthly GDP. Quarterly growth is compounded to an annual rate. SAAR means the published level is seasonally adjusted at an annual rate.', 'BEA and national statistical sources via FRED. Real GDP is quarterly and revised after initial estimates; Q1 2025 is not a clean January-only baseline.');

  const applicationRows = (config.applications ?? []).map(def => {
    const s = series.get(def.id), d = latestDate(s);
    return row(def, [def.label, valueAt(s, d), growth(s, d, 1), growth(s, d, 12), d]);
  });
  addSection('applications', 'Business applications', 'Business applications', 'BUSINESS ACTIVITY', [text('Applications'), number('Level', 0), number('MoM (%)'), number('YoY (%)'), date('Period', 'monthly')], applicationRows, 'Monthly applications, seasonally adjusted. High-propensity applications are a subset of total applications, not additional business formations.', 'U.S. Census Bureau via FRED.');
  addSection('claims', 'Jobless claims', 'Initial and continued claims', 'LABOR MARKET', [text('Measure'), number('Claims', 0), number('1 week ago', 0), number('52 weeks ago', 0), date('Week ending')], (config.claims ?? []).map(def => {
    const s = series.get(def.id), d = latestDate(s);
    return row(def, [def.label, valueAt(s, d), valueAt(s, dayShift(d, -7)), valueAt(s, dayShift(d, -364)), d]);
  }), 'Seasonally adjusted. Continued claims generally refer to an earlier week than initial claims.', 'U.S. Employment and Training Administration via FRED. Comparisons require the exact week; missing dates remain unavailable.');
  addSection('markets', 'Stock market', 'Stock market indexes', 'FINANCIAL MARKETS', [text('Index'), number('Close'), number('1m (%)'), number('YTD (%)'), number('1y (%)'), date('Close date')], (config.markets ?? []).map(def => {
    const s = series.get(def.id), d = latestDate(s), current = valueAt(s, d);
    const change = target => percent(current, observationAtOrBefore(s, target)?.value);
    return row(def, [def.label, current, change(monthShift(d, -1)), change(`${Number(d.slice(0, 4)) - 1}-12-31`), change(monthShift(d, -12)), d]);
  }), 'Daily closing price indexes, not live prices. Changes exclude dividends. Market series are not seasonally adjusted.', 'S&P Dow Jones Indices and Nasdaq via FRED. Calendar lookbacks use a preceding available close within seven days.');

  const budgetRows = [];
  const monthlyBudget = (config.budget ?? []).find(def => def.id === 'MTSDS133FMS');
  if (monthlyBudget) {
    const s = series.get(monthlyBudget.id), d = latestDate(s);
    const sum = (start, end) => {
      let total = 0;
      for (let m = start; m <= end; m = monthShift(m, 1)) { const n = valueAt(s, m); if (n === null) return null; total += n; }
      return total;
    };
    const fiscalStart = `${Number(d.slice(0, 4)) - (Number(d.slice(5, 7)) < 10 ? 1 : 0)}-10-01`;
    for (const [label, value] of [['Monthly deficit', valueAt(s, d)], ['Fiscal year to date deficit', sum(fiscalStart, d)], ['Trailing 12 months deficit', sum(monthShift(d, -11), d)]]) budgetRows.push(row(monthlyBudget, [label, scaled(value, -0.001), 'USD billions', d]));
  }
  const annualBudget = (config.budget ?? []).find(def => def.id === 'FYFSGDA188S');
  if (annualBudget) { const s = series.get(annualBudget.id), d = latestDate(s); budgetRows.push(row(annualBudget, ['Fiscal year deficit / GDP', scaled(valueAt(s, d), -1), '% of GDP', `FY ${d.slice(0, 4)}`])); }
  addSection('budget', 'Federal budget', 'Federal deficit measures', 'FISCAL POSITION', [text('Measure'), number('Deficit'), text('Units'), text('Period ending')], budgetRows, 'Positive values indicate a deficit; negative values indicate a surplus. Fiscal year to date begins in October. Published budget balances are NSA.', 'Treasury and OMB via FRED. Monthly balances are summed only when every required month is available.');
  addSection('participation', 'Participation', 'Prime-age participation and employment', 'LABOR MARKET', rateColumns('Measure'), rateRows(config.participation ?? []), 'People ages 25–54. Seasonally adjusted. Participation includes employed people and unemployed people seeking work.', 'BLS household survey via FRED. pp means percentage points.');
  addSection('context', 'Labor context', 'Job openings, quits, underemployment and wages', 'LABOR MARKET', [text('Measure'), number('Value', 2), text('Units'), date('Period', 'monthly')], [...(config.extra ?? []).filter(def => def.id !== 'UMCSENT'), ...(config.wages ?? [])].map(def => {
    const s = series.get(def.id), d = latestDate(s); return row(def, [def.label, valueAt(s, d), def.units, d]);
  }), 'Published seasonal adjustment is retained. Job openings and quits come from JOLTS; U-6 is a broader measure of labor underutilization. Wages are nominal dollars per hour.', 'BLS via FRED. Observation months differ across releases.');

  const defaultWar = ['GASREGW', 'GASDESW', 'DCOILWTICO', 'DCOILBRENTEU', 'SP500', 'DJIA', 'NASDAQCOM', 'CPIAUCSL', 'PCEPI', 'UNRATE', 'PAYEMS'];
  const warIds = [...(catalog.war ?? defaultWar), 'CPIAUCSL', 'CPILFESL', 'PCEPI', 'PCEPILFE', 'PAYEMS', 'UNRATE', 'ICSA'].map(item => typeof item === 'string' ? item : item.id);
  const warDefs = unique(warIds.filter(id => definitions.has(id)).map(id => definitions.get(id)));
  addSection('war', 'Since Iran War began', 'Changes since February 28, 2026', 'BEFORE & AFTER', [text('Indicator'), number('Baseline value', 3), date('Baseline observation'), number('Latest value', 3), date('Latest observation'), number('Absolute change', 3), number('Change (%)'), text('Unit / adjustment')], warDefs.map(def => {
    const s = series.get(def.id), d = latestDate(s), base = prewarBaseline(s, def);
    const multiplier = def.multiplier ?? 1;
    const latest = scaled(valueAt(s, d), multiplier), baseline = scaled(base?.value, multiplier);
    const unit = multiplier === 1000 && /person/i.test(def.units ?? '') ? 'People' : (def.units || (def.id === 'UNRATE' ? 'Percent' : ''));
    const label = { CPIAUCSL: 'CPI price index', CPILFESL: 'Core CPI price index', PCEPI: 'PCE price index', PCEPILFE: 'Core PCE price index', PAYEMS: 'Total nonfarm payroll jobs', UNRATE: 'Unemployment rate (U-3)', ICSA: 'Initial jobless claims' }[def.id] ?? def.label;
    return row(def, [label, baseline, base?.date ?? null, latest, d, subtract(latest, baseline), percent(latest, baseline), `${unit} · ${def.sa ?? 'SA'}`]);
  }), 'Reference date: February 28, 2026. Daily and weekly baselines are the last available observation before that date; monthly baselines use January 2026 because February spans the start of the war. Each baseline is shown explicitly. These comparisons describe changes over time and do not attribute them to the war.', 'Sources via FRED. Daily baselines must be within 7 days and weekly baselines within 14 days of the cutoff; missing monthly baselines stay unavailable. Percentage-point changes in rate series appear under absolute change; percent change is relative to the baseline.');

  const kpis = [];
  if (series.has('PAYEMS')) {
    const s = series.get('PAYEMS'), d = latestDate(s), value = averageJobChange(s, d, 1, definitions.get('PAYEMS').multiplier ?? 1000);
    kpis.push({ label: 'Nonfarm payrolls', value, digits: 0, prefix: finite(value) && value >= 0 ? '+' : '', suffix: '', detail: `Monthly job change · ${monthLabel(d)} · SA`, source: sourceFor(definitions.get('PAYEMS')) });
  }
  if (series.has('UNRATE')) { const s = series.get('UNRATE'), d = latestDate(s); kpis.push({ label: 'Unemployment rate', value: valueAt(s, d), digits: 1, prefix: '', suffix: '%', detail: `Overall U-3 · ${monthLabel(d)} · SA`, source: sourceFor(definitions.get('UNRATE')) }); }
  if (series.has('CPIAUCSL')) { const s = series.get('CPIAUCSL'), d = latestDate(s); kpis.push({ label: 'CPI inflation', value: growth(s, d, 12), digits: 1, prefix: '', suffix: '%', detail: `Year-over-year · ${monthLabel(d)} · SA index`, source: sourceFor(definitions.get('CPIAUCSL')) }); }
  return { retrieved, retrievedAt, warStart: WAR_START, kpis, sections, notes: catalog.notes ?? {} };
}

export async function refreshDashboard({ config, catalog, outputDir, cacheDir, fetchSeries = fetchFredSeries, clock = () => new Date() }) {
  const definitions = dashboardDefinitions(config, catalog), queue = [...definitions.keys()], raw = new Map(), errors = [];
  const end = clock().toISOString().slice(0, 10);
  await Promise.all(Array.from({ length: Math.min(4, queue.length) }, async () => {
    while (queue.length) {
      const id = queue.shift();
      try { raw.set(id, await fetchSeries(id, { start: '2020-01-01', end, cacheDir })); }
      catch (error) { errors.push(`${id}: ${error.message}`); }
    }
  }));
  if (errors.length) throw new Error(`Refresh aborted; published files were not changed. ${errors.length} source(s) failed:\n${errors.join('\n')}`);
  const dashboard = buildDashboard(raw, catalog, clock(), config);
  const snapshotId = randomUUID();
  dashboard.snapshotId = snapshotId;
  const exported = { retrieved: dashboard.retrieved, retrievedAt: dashboard.retrievedAt, snapshotId, series: {} };
  for (const [id, def] of definitions) exported.series[id] = { ...def, ...raw.get(id) };
  // Both complete payloads are validated before either published path is touched.
  const payloads = [['series.json', exported], ['data.json', dashboard]].map(([name, value]) => [name, `${JSON.stringify(value, null, 2)}\n`]);
  await mkdir(outputDir, { recursive: true });
  const temporary = [];
  try {
    for (const [name, content] of payloads) {
      const target = join(outputDir, name), temp = `${target}.${process.pid}.${snapshotId}.tmp`;
      temporary.push({ target, temp });
      await writeFile(temp, content, { flag: 'wx' });
    }
    for (const { target, temp } of temporary) await rename(temp, target);
  } finally {
    await Promise.all(temporary.map(({ temp }) => unlink(temp).catch(error => { if (error.code !== 'ENOENT') throw error; })));
  }
  return { seriesCount: raw.size, sectionCount: dashboard.sections.length, retrievedAt: dashboard.retrievedAt };
}

export async function main(argv = process.argv.slice(2)) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (key === '--help') { console.log('Usage: node refresh_dashboard.mjs [--output-dir docs] [--cache-dir cache/dashboard] [--config config.json] [--catalog dashboard_catalog.json]\nFetches every configured source online, computes the public tables and saves data.json plus series.json. A failed source aborts publication. No API key or Codex runtime is required.'); return; }
    if (!['--output-dir', '--cache-dir', '--config', '--catalog'].includes(key) || !argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`Unknown option or missing value: ${key}`);
    args[key.slice(2)] = argv[++i];
  }
  const config = JSON.parse(await readFile(args.config ?? join(HERE, 'config.json'), 'utf8'));
  const catalog = JSON.parse(await readFile(args.catalog ?? join(HERE, 'dashboard_catalog.json'), 'utf8'));
  const result = await refreshDashboard({ config, catalog, outputDir: resolve(args['output-dir'] ?? join(HERE, 'docs')), cacheDir: resolve(args['cache-dir'] ?? join(HERE, 'cache', 'dashboard')) });
  console.log(`Refreshed ${result.seriesCount} sources and ${result.sectionCount} tables at ${result.retrievedAt}.`);
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main().catch(error => { console.error(error.message); process.exitCode = 1; });
