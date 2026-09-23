import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { monthShift } from './data.mjs';
import { elapsedMonths, employmentComparison, deriveEmployment, prewarBaseline, priceComparison, observationAtOrBefore, buildDashboard, refreshDashboard, dashboardDefinitions } from './refresh_dashboard.mjs';

const s = (...points) => ({ observations: points.map(([date, value]) => ({ date, value })) });
const monthly = (months = 68, start = '2021-01-01', initial = 100, change = 2) => ({ observations: Array.from({ length: months }, (_, i) => ({ date: monthShift(start, i), value: initial + i * change })) });
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`);
const fixed = new Date('2026-09-23T14:20:00.000Z');
const definition = (id, group = 'employment', extras = {}) => ({ id, group, label: id, sa: 'SA', frequency: 'monthly', units: 'Thousands of persons', ...extras });

// Counts are 48 January-to-January changes, not 49 monthly observations.
test('employment totals and monthly averages use exact January levels and elapsed months', () => {
  const stats = employmentComparison(monthly());
  assert.equal(stats.period, '2026-08-01');
  assert.equal(stats.level, 234000);
  assert.equal(stats.monthly, 2000);
  assert.equal(stats.total2021To2025, 96000);
  assert.equal(stats.average2021To2025, 2000);
  assert.equal(stats.totalSince2025, 38000);
  assert.equal(stats.averageSince2025, 2000);
  assert.equal(stats.monthsSince2025, 19);
  assert.equal(stats.totalSince2021, 134000);
  assert.equal(elapsedMonths('2021-01-01', '2025-01-01'), 48);
  assert.equal(employmentComparison(monthly(49)).averageSince2025, null);
  assert.equal(employmentComparison(monthly(49)).totalSince2025, 0);
});

test('missing interior employment months preserve endpoint totals but suppress monthly averages', () => {
  const input = monthly();
  input.observations = input.observations.filter(point => !['2023-06-01', '2025-06-01'].includes(point.date));
  const stats = employmentComparison(input);
  assert.equal(stats.total2021To2025, 96000);
  assert.equal(stats.totalSince2025, 38000);
  assert.equal(stats.average2021To2025, null);
  assert.equal(stats.averageSince2025, null);
  input.observations = input.observations.filter(point => point.date !== '2021-01-01');
  assert.equal(employmentComparison(input).totalSince2021, null);
  assert.equal(employmentComparison(input).total2021To2025, null);
});

test('national and catalog employment scale raw thousands exactly once, regardless of display override', () => {
  const config = { employment: [definition('PAYEMS', 'employment', { units_override: 'persons' })] };
  const data = buildDashboard({ PAYEMS: monthly() }, { series: [] }, fixed, config);
  assert.equal(data.sections[0].rows[0].values[1], 234000);
  assert.equal(data.kpis[0].value, 2000);
  assert.equal(data.kpis[0].source, 'https://fred.stlouisfed.org/series/PAYEMS');
  assert.equal(dashboardDefinitions(config, {}).get('PAYEMS').multiplier, 1000);
});

test('derived auto jobs use only common dates and normalize each component once', () => {
  const defs = new Map([['MFG', definition('MFG', 'manuf_auto', { multiplier: 1000 })], ['DEALERS', definition('DEALERS', 'manuf_auto', { multiplier: 1000 })]]);
  const series = { MFG: s(['2025-01-01', 10], ['2025-02-01', 11], ['2025-03-01', 12]), DEALERS: s(['2025-01-01', 20], ['2025-02-01', 21]) };
  const derived = deriveEmployment({ id: 'TOTAL', components: ['MFG', 'DEALERS'] }, series, defs);
  assert.deepEqual(derived.observations, [{ date: '2025-01-01', value: 30000 }, { date: '2025-02-01', value: 32000 }]);
  const result = employmentComparison(derived, undefined, 1);
  assert.equal(result.level, 32000);
  assert.equal(result.monthly, 2000);
  const catalog = { series: [...defs.values()], derived: [{ id: 'TOTAL', label: 'Total auto jobs', group: 'manuf_auto', sa: 'SA', components: ['MFG', 'DEALERS'] }] };
  const dashboard = buildDashboard(series, catalog, fixed);
  const row = dashboard.sections.find(group => group.key === 'manufacturing').rows.find(item => item.id === 'TOTAL');
  assert.equal(row.values[1], 32000);
  assert.equal(row.values.at(-1), '2025-02-01');
  assert.equal(row.sources.length, 2);
});

test('war baselines exclude the start date and incomplete February monthly period', () => {
  const daily = s(['2026-02-26', 90], ['2026-02-27', 100], ['2026-02-28', 120], ['2026-03-02', 130]);
  assert.deepEqual(prewarBaseline(daily, { frequency: 'daily' }), { date: '2026-02-27', value: 100 });
  const weekly = s(['2026-02-23', 3], ['2026-03-02', 3.5]);
  assert.deepEqual(prewarBaseline(weekly, { frequency: 'weekly' }), { date: '2026-02-23', value: 3 });
  const monthlyPrices = s(['2025-12-01', 9], ['2026-01-01', 10], ['2026-02-01', 11], ['2026-03-01', 12]);
  assert.deepEqual(prewarBaseline(monthlyPrices, { frequency: 'monthly' }), { date: '2026-01-01', value: 10 });
  assert.equal(prewarBaseline(s(['2025-12-01', 9], ['2026-02-01', 11]), { frequency: 'monthly' }), null);
  assert.equal(prewarBaseline(s(['2026-01-01', 90]), { frequency: 'daily' }), null);
});

test('war monthly macro values retain actual unit and percentage-point changes', () => {
  const catalog = { series: [definition('UNRATE', 'unemployment', { units: 'Percent', multiplier: 1 })], war: ['UNRATE'] };
  const data = buildDashboard({ UNRATE: s(['2026-01-01', 4], ['2026-02-01', 4.1], ['2026-08-01', 4.5]) }, catalog, fixed);
  const row = data.sections.find(section => section.key === 'war').rows[0];
  assert.equal(row.values[1], 4);
  assert.equal(row.values[2], '2026-01-01');
  assert.equal(row.values[5], 0.5);
  close(row.values[6], 12.5);
  assert.equal(row.values[7], 'Percent · SA');
});

test('basic good prices remain nominal dollars and NSA; monthly and weekly lookbacks differ', () => {
  const prices = s(['2025-08-01', 5], ['2026-07-01', 6], ['2026-08-01', 6.5]);
  const result = priceComparison(prices, { frequency: 'monthly', sa: 'NSA' });
  assert.equal(result.current, 6.5);
  assert.equal(result.change, 0.5);
  close(result.yearChange, 30);
  const weekly = priceComparison(s(['2025-09-22', 3], ['2026-09-14', 3.5], ['2026-09-21', 4]), { frequency: 'weekly' });
  assert.equal(weekly.change, 0.5);
  close(weekly.yearChange, 100 / 3);
  const catalog = { series: [definition('BEEF', 'prices', { units: 'USD per pound', multiplier: 1, sa: 'NSA' })] };
  const row = buildDashboard({ BEEF: prices }, catalog, fixed).sections.find(group => group.key === 'prices').rows[0];
  assert.equal(row.values[1], 6.5);
  assert.equal(row.values[4], 'USD per pound');
  assert.equal(row.values[6], 'NSA');
});

test('quarterly GDP annualizes by compounding and labels Q1 comparisons', () => {
  const series = { GDP: s(['2021-01-01', 100], ['2025-01-01', 120], ['2025-04-01', 121], ['2026-01-01', 125], ['2026-04-01', 126]) };
  const catalog = { series: [definition('GDP', 'gdp', { frequency: 'quarterly', units: 'Billions of real USD', multiplier: 1, sa: 'SAAR' })] };
  const section = buildDashboard(series, catalog, fixed).sections[0], values = section.rows[0].values;
  close(values[3], ((126 / 125) ** 4 - 1) * 100);
  close(values[4], (126 / 121 - 1) * 100);
  close(values[5], 20);
  close(values[6], 5);
  assert.equal(section.columns.at(-1).frequency, 'quarterly');
});

test('market lookup follows calendar cutoff, never a future close or stale quote', () => {
  const input = s(['2025-12-26', 50], ['2025-12-30', 55], ['2026-01-02', 60]);
  assert.deepEqual(observationAtOrBefore(input, '2025-12-31'), { date: '2025-12-30', value: 55 });
  assert.equal(observationAtOrBefore(input, '2026-02-01'), null);
});

test('unconfigured PCE components publish unavailable values rather than retained manual data', () => {
  const config = { pce: [{ id: null, label: 'Core Goods', note: 'old manually supplied value' }] };
  const data = buildDashboard({}, { series: [] }, fixed, config);
  assert.deepEqual(data.sections[0].rows[0].values, ['PCE · Core Goods', null, null, null, null]);
  assert.match(data.sections[0].rows[0].note, /not configured/);
  assert.equal(data.retrievedAt, '2026-09-23T14:20:00.000Z');
});

test('failed required fetch leaves the existing publication and timestamp unchanged', async () => {
  const outputDir = await mkdtemp(join(tmpdir(), 'dashboard-failure-'));
  try {
    await writeFile(join(outputDir, 'data.json'), 'existing dashboard');
    await writeFile(join(outputDir, 'series.json'), 'existing sources');
    const catalog = { series: [definition('A', 'prices'), definition('B', 'prices')] };
    await assert.rejects(refreshDashboard({ config: {}, catalog, outputDir, clock: () => fixed, fetchSeries: async id => { if (id === 'B') throw new Error('HTTP 500'); return monthly(); } }), /published files were not changed/);
    assert.equal(await readFile(join(outputDir, 'data.json'), 'utf8'), 'existing dashboard');
    assert.equal(await readFile(join(outputDir, 'series.json'), 'utf8'), 'existing sources');
    assert.deepEqual((await readdir(outputDir)).sort(), ['data.json', 'series.json']);
  } finally { await rm(outputDir, { recursive: true, force: true }); }
});

test('successful refresh limits concurrency, exports provenance and pairs snapshot IDs', async () => {
  const outputDir = await mkdtemp(join(tmpdir(), 'dashboard-success-'));
  let active = 0, peak = 0;
  try {
    const catalog = { series: Array.from({ length: 9 }, (_, i) => definition(`A${i}`, 'prices', { multiplier: 1 })) };
    const result = await refreshDashboard({ config: {}, catalog, outputDir, clock: () => fixed, fetchSeries: async id => {
      active++; peak = Math.max(peak, active);
      await new Promise(resolve => setTimeout(resolve, 5));
      active--;
      return { ...monthly(), id, sourceUrl: `https://fred.stlouisfed.org/series/${id}`, fetchedAt: fixed.toISOString() };
    } });
    assert.equal(peak, 4);
    assert.equal(result.seriesCount, 9);
    const published = JSON.parse(await readFile(join(outputDir, 'data.json'), 'utf8'));
    const raw = JSON.parse(await readFile(join(outputDir, 'series.json'), 'utf8'));
    assert.equal(published.retrievedAt, fixed.toISOString());
    assert.equal(raw.snapshotId, published.snapshotId);
    assert.equal(raw.series.A0.fetchedAt, fixed.toISOString());
    assert.equal(raw.series.A0.observations.length, 68);
    assert.deepEqual((await readdir(outputDir)).sort(), ['data.json', 'series.json']);
  } finally { await rm(outputDir, { recursive: true, force: true }); }
});

test('validation rejects nonfinite, unordered or future raw data before publication', () => {
  const catalog = { series: [definition('A', 'prices')] };
  for (const series of [s(['2026-10-01', 1]), s(['2026-01-01', Infinity]), s(['2026-02-01', 1], ['2026-01-01', 1]), s(['2026-02-30', 1])]) {
    assert.throws(() => buildDashboard({ A: series }, catalog, fixed), /Invalid/);
  }
  assert.throws(() => buildDashboard({}, catalog, fixed), /Missing observations/);
});
