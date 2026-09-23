import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  fetchFredSeries, parseFredCsv, monthShift, valueAt, latestDate, commonLatest,
  growth, averageJobChange, meanJobChangeBetween, decemberGrowth, yearlyMean,
} from './data.mjs';

const series = (...entries) => ({ observations: entries.map(([date, value]) => ({ date, value })) });
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`);
const response = (csv, status = 200) => ({ ok: status >= 200 && status < 300, status, text: async () => csv });
const csv = 'observation_date,PAYEMS\n2023-01-01,100\n2023-02-01,103\n2023-03-01,109\n';

test('CSV accepts BOM, quoted fields and CRLF; sorts observations and skips missing/future values', () => {
  assert.deepEqual(parseFredCsv('\uFEFF"observation_date","PAYEMS"\r\n2023-03-01,109\r\n2023-02-01,.\r\n2023-01-01,1e2\r\n9999-01-01,110\r\n', 'PAYEMS', '9999-12-31'), [
    { date: '2023-01-01', value: 100 }, { date: '2023-03-01', value: 109 },
  ]);
  assert.deepEqual(parseFredCsv(csv, 'PAYEMS', '2023-02-01').map(x => x.date), ['2023-01-01', '2023-02-01']);
  assert.deepEqual(parseFredCsv('DATE,PAYEMS\n2023-01-01,-1.5\n', 'PAYEMS'), [{ date: '2023-01-01', value: -1.5 }]);
});

test('CSV rejects wrong headers, duplicates, invalid dates, values and broken rows', () => {
  for (const input of [
    'DATE,OTHER\n2023-01-01,100',
    'DATE,PAYEMS\n2023-01-01,100\n2023-01-01,.',
    'DATE,PAYEMS\n2023-02-30,100',
    'DATE,PAYEMS\n2023-01-01,Infinity',
    'DATE,PAYEMS\n2023-01-01,not-a-number',
    'DATE,PAYEMS\n2023-01-01,1,2',
    '"DATE,PAYEMS',
  ]) assert.throws(() => parseFredCsv(input, 'PAYEMS'));
  assert.throws(() => parseFredCsv(csv, '../PAYEMS'));
});

test('FRED empty observations and market holidays are missing, never numeric zero', () => {
  const text = 'observation_date,SP500\n2025-12-24,6000\n2025-12-25,\n2025-12-26,  \n2025-12-29,.\n2025-12-30,0\n';
  assert.deepEqual(parseFredCsv(text, 'SP500', '2025-12-31'), [
    {date: '2025-12-24', value: 6000}, {date: '2025-12-30', value: 0},
  ]);
});

test('month arithmetic is calendar-based, handles leap years and validates input', () => {
  assert.equal(monthShift('2024-03-31', -1), '2024-02-29');
  assert.equal(monthShift('2023-01-31', 1), '2023-02-28');
  assert.equal(monthShift('2023-01-01', -13), '2021-12-01');
  assert.throws(() => monthShift('2023-02-30', 1));
  assert.throws(() => monthShift('2023-02-01', 0.5));
});

test('lookups never carry forward, and commonLatest finds actual intersection', () => {
  const a = series(['2023-03-01', 2], ['2023-01-01', 0]);
  const b = series(['2023-01-01', 7], ['2023-02-01', 8]);
  assert.equal(valueAt(a, '2023-01-01'), 0);
  assert.equal(valueAt(a, '2023-02-01'), null);
  assert.equal(latestDate(a), '2023-03-01');
  assert.equal(latestDate(series()), null);
  assert.equal(commonLatest([a, b]), '2023-01-01');
  assert.equal(commonLatest([a, series()]), null);
  assert.equal(commonLatest([]), null);
});

test('growth returns percent, annualizes endpoint ratios, and handles invalid index levels', () => {
  const a = series(['2023-01-01', 100], ['2023-04-01', 102], ['2024-01-01', 110]);
  close(growth(a, '2024-01-01', 12), 10);
  close(growth(a, '2023-04-01', 3, true), (1.02 ** 4 - 1) * 100);
  assert.equal(growth(a, '2023-03-01', 1), null);
  assert.equal(growth(series(['2023-01-01', 0], ['2023-02-01', 1]), '2023-02-01', 1), null);
  assert.equal(growth(series(['2023-01-01', 1], ['2023-02-01', -1]), '2023-02-01', 1), null);
  assert.equal(growth(series(['2023-01-01', -1], ['2023-02-01', 1]), '2023-02-01', 1), null);
  assert.equal(growth(series(['2023-01-01', 1], ['2023-02-01', 0]), '2023-02-01', 1), -100);
  assert.throws(() => growth(a, '2024-01-01', 0));
});

test('average job changes require every month and scale thousands to persons', () => {
  const a = series(['2023-01-01', 100], ['2023-02-01', 103], ['2023-03-01', 109]);
  assert.equal(averageJobChange(a, '2023-03-01', 2), 4500);
  assert.equal(averageJobChange(a, '2023-03-01', 2, 1), 4.5);
  assert.equal(averageJobChange(a, '2023-03-01', 3), null);
  assert.equal(averageJobChange(series(['2023-01-01', 100], ['2023-03-01', 109]), '2023-03-01', 2), null);
  assert.equal(averageJobChange(series(['2023-01-01', 0], ['2023-02-01', -1]), '2023-02-01', 1), -1000);
  assert.throws(() => averageJobChange(a, '2023-03-01', 0));
});

test('term baseline is start month, includes changes beginning the following month', () => {
  const a = series(['2025-01-01', 100], ['2025-02-01', 103], ['2025-03-01', 107]);
  assert.equal(meanJobChangeBetween(a, '2025-01-01', '2025-03-01'), 3500);
  assert.equal(meanJobChangeBetween(a, '2025-01-01', '2025-01-01'), null);
  assert.equal(meanJobChangeBetween(a, '2025-03-01', '2025-01-01'), null);
  assert.equal(meanJobChangeBetween(a, '2025-01-02', '2025-03-01'), null);
});

test('December growth and yearly means have strict calendar completeness', () => {
  close(decemberGrowth(series(['2022-12-01', 100], ['2023-12-01', 105]), 2023), 5);
  assert.equal(decemberGrowth(series(['2022-12-01', 100]), 2023), null);
  const a = series(...Array.from({ length: 12 }, (_, i) => [`2023-${String(i + 1).padStart(2, '0')}-01`, i + 1]));
  assert.equal(yearlyMean(a, 2023), 6.5);
  a.observations.push({ date: '2023-01-02', value: 3 });
  assert.equal(yearlyMean(a, 2023), null);
  a.observations.pop();
  a.observations.pop();
  assert.equal(yearlyMean(a, 2023), null);
});

test('successful fetch writes atomic cache; offline uses cache without networking', async () => {
  const cacheDir = await mkdtemp(join(tmpdir(), 'gene-data-test-'));
  try {
    let calls = 0;
    const result = await fetchFredSeries('PAYEMS', {
      start: '2023-01-01', end: '2023-03-01', cacheDir,
      fetchImpl: async (url, options) => {
        calls++;
        const parsed = new URL(url);
        assert.equal(parsed.searchParams.get('id'), 'PAYEMS');
        assert.equal(parsed.searchParams.get('cosd'), '2023-01-01');
        assert.ok(options.signal instanceof AbortSignal);
        return response(csv);
      },
    });
    assert.equal(calls, 1);
    assert.equal(result.observations.length, 3);
    assert.equal(result.sourceUrl, 'https://fred.stlouisfed.org/series/PAYEMS');
    assert.ok(Number.isFinite(Date.parse(result.fetchedAt)));
    assert.deepEqual(await readdir(cacheDir), ['PAYEMS.json']);
    const cached = JSON.parse(await readFile(join(cacheDir, 'PAYEMS.json'), 'utf8'));
    assert.equal(cached.requestedStart, '2023-01-01');
    const offline = await fetchFredSeries('PAYEMS', {
      start: '2023-02-01', end: '2023-03-01', cacheDir, offline: true,
      fetchImpl: async () => { throw new Error('Network must never run in offline mode'); },
    });
    assert.deepEqual(offline.observations, result.observations.slice(1));
    assert.equal(offline.fetchedAt, result.fetchedAt);
    await assert.rejects(fetchFredSeries('PAYEMS', { start: '2022-01-01', end: '2023-03-01', cacheDir, offline: true }), /does not cover/);
    let attempts = 0;
    await assert.rejects(fetchFredSeries('PAYEMS', {
      start: '2023-01-01', end: '2023-03-01', cacheDir, retryDelayMs: 0,
      fetchImpl: async () => { attempts++; throw new Error('Network failure'); },
    }), /Network failure/);
    assert.equal(attempts, 3); // No silent fallback to the existing cache.
    cached.observations.reverse();
    await writeFile(join(cacheDir, 'PAYEMS.json'), JSON.stringify(cached));
    await assert.rejects(fetchFredSeries('PAYEMS', { start: '2023-01-01', end: '2023-03-01', cacheDir, offline: true }), /unordered/);
  } finally { await rm(cacheDir, { recursive: true, force: true }); }
});

test('HTTP retry is bounded; ordinary client failures do not retry', async () => {
  let calls = 0;
  const options = { start: '2023-01-01', end: '2023-03-01', retryDelayMs: 0 };
  const recovered = await fetchFredSeries('PAYEMS', { ...options, fetchImpl: async () => response(++calls < 3 ? '' : csv, calls < 3 ? 503 : 200) });
  assert.equal(calls, 3);
  assert.equal(recovered.observations.length, 3);
  calls = 0;
  await assert.rejects(fetchFredSeries('PAYEMS', { ...options, fetchImpl: async () => { calls++; return response('', 404); } }), /HTTP 404/);
  assert.equal(calls, 1);
  calls = 0;
  await assert.rejects(fetchFredSeries('PAYEMS', { ...options, fetchImpl: async () => { calls++; return response('', 429); } }), /HTTP 429/);
  assert.equal(calls, 3);
  await assert.rejects(fetchFredSeries('PAYEMS', { ...options, fetchImpl: async () => response('DATE,OTHER\n2023-01-01,1') }), /Unexpected CSV headers/);
  await assert.rejects(fetchFredSeries('PAYEMS', { ...options, fetchImpl: async () => response('DATE,PAYEMS\n2023-01-01,.') }), /No usable/);
  await assert.rejects(fetchFredSeries('../PAYEMS', options), /Invalid FRED series ID/);
  await assert.rejects(fetchFredSeries('PAYEMS', { ...options, offline: true }), /requires cacheDir/);
});
