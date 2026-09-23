/**
 * Public FRED CSV transport and calendar-aware economic calculations.
 * Node.js 20+; built-in modules only. Growth results are percent, e.g. 2.5 = 2.5%.
 */
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const ID = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;
const NUMERIC = /^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$/;
const today = () => new Date().toISOString().slice(0, 10);

function assertDate(value, label = 'date') {
  if (typeof value !== 'string' || !DATE.test(value)) throw new Error(`Invalid ${label}: ${value}`);
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new Error(`Invalid ${label}: ${value}`);
  }
  return value;
}

function assertId(id) {
  if (typeof id !== 'string' || !ID.test(id)) throw new Error(`Invalid FRED series ID: ${id}`);
  return id;
}

function observationMap(series) {
  if (!series || !Array.isArray(series.observations)) throw new TypeError('Expected a series with observations');
  return new Map(series.observations.map(({ date, value }) => [date, value]));
}

/** Shift an ISO date by calendar months, clamping to the target month's last day. */
export function monthShift(date, n) {
  assertDate(date);
  if (!Number.isInteger(n)) throw new Error('Month shift must be an integer');
  const [year, month, day] = date.split('-').map(Number);
  const target = new Date(Date.UTC(year, month - 1 + n, 1));
  if (!Number.isFinite(target.getTime())) throw new Error('Month shift is outside the supported date range');
  const daysInMonth = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(day, daysInMonth));
  return assertDate(target.toISOString().slice(0, 10));
}

/** A deliberately small CSV reader that supports quoted fields and CRLF. */
function csvRows(text) {
  const rows = [];
  let row = [], field = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { field += '"'; i++; }
      else if (quoted || field.length === 0) quoted = !quoted;
      else throw new Error('Malformed FRED CSV quoting');
    } else if (char === ',' && !quoted) {
      row.push(field); field = '';
    } else if ((char === '\r' || char === '\n') && !quoted) {
      row.push(field);
      if (row.some(value => value.trim() !== '')) rows.push(row);
      row = []; field = '';
      if (char === '\r' && text[i + 1] === '\n') i++;
    } else field += char;
  }
  if (quoted) throw new Error('Unclosed quote in FRED CSV');
  row.push(field);
  if (row.some(value => value.trim() !== '')) rows.push(row);
  return rows;
}

/** Parse, validate, sort and filter FRED observations; missing "." or empty values are omitted. */
export function parseFredCsv(csv, id, end = today()) {
  assertId(id); assertDate(end, 'end date');
  if (typeof csv !== 'string') throw new TypeError('FRED CSV must be text');
  const rows = csvRows(csv.replace(/^\uFEFF/, ''));
  const header = rows.shift()?.map(value => value.trim());
  if (!header || header.length !== 2 || !['observation_date', 'DATE'].includes(header[0]) || header[1] !== id) {
    throw new Error(`Unexpected CSV headers for ${id}; expected observation_date,${id}`);
  }
  const observations = [];
  const seen = new Set();
  const cutoff = end < today() ? end : today();
  for (const row of rows) {
    if (row.length !== 2) throw new Error(`Malformed CSV row for ${id}`);
    const [date, raw] = row.map(value => value.trim());
    assertDate(date, `observation date in ${id}`);
    if (seen.has(date)) throw new Error(`Duplicate observation date in ${id}: ${date}`);
    seen.add(date);
    if (raw === '.' || raw === '') continue;
    if (!NUMERIC.test(raw) || !Number.isFinite(Number(raw))) throw new Error(`Invalid value in ${id} on ${date}: ${raw}`);
    if (date <= cutoff) observations.push({ date, value: Number(raw) });
  }
  observations.sort((a, b) => a.date.localeCompare(b.date));
  return observations;
}

async function writeCache(cacheDir, id, data) {
  await mkdir(cacheDir, { recursive: true });
  const target = join(cacheDir, `${id}.json`);
  const temporary = `${target}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(data, null, 2)}\n`, { flag: 'wx' });
    await rename(temporary, target);
  } finally {
    await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; });
  }
}

async function readCache(cacheDir, id, start, end) {
  if (!cacheDir) throw new Error('Offline mode requires cacheDir');
  let cached;
  try { cached = JSON.parse(await readFile(join(cacheDir, `${id}.json`), 'utf8')); }
  catch (error) { throw new Error(`Cannot read offline cache for ${id}: ${error.message}`, { cause: error }); }
  if (cached.id !== id || cached.sourceUrl !== `https://fred.stlouisfed.org/series/${id}` || !Array.isArray(cached.observations)) {
    throw new Error(`Invalid offline cache for ${id}`);
  }
  assertDate(cached.requestedStart, 'cache start'); assertDate(cached.requestedEnd, 'cache end');
  if (cached.requestedStart > start || cached.requestedEnd < end) {
    throw new Error(`Offline cache for ${id} does not cover ${start} through ${end}; refresh online first`);
  }
  if (typeof cached.fetchedAt !== 'string' || !Number.isFinite(Date.parse(cached.fetchedAt))) {
    throw new Error(`Invalid cache retrieval date for ${id}`);
  }
  let previous;
  for (const point of cached.observations) {
    assertDate(point.date, 'cached observation date');
    if (typeof point.value !== 'number' || !Number.isFinite(point.value) || (previous && point.date <= previous)) {
      throw new Error(`Invalid or unordered cached observations for ${id}`);
    }
    if (point.date < cached.requestedStart || point.date > cached.requestedEnd) {
      throw new Error(`Cached observations outside requested range for ${id}`);
    }
    previous = point.date;
  }
  return {
    id,
    observations: cached.observations.filter(point => point.date >= start && point.date <= end),
    sourceUrl: cached.sourceUrl,
    fetchedAt: cached.fetchedAt,
  };
}

/**
 * Download live public data without an API key. At most two retries for transient
 * failures, each attempt limited to 25 seconds. Offline reads are opt-in and
 * errors never silently substitute old cached data. fetchImpl/retryDelayMs are
 * dependency injection hooks for tests; normal callers should omit them.
 */
export async function fetchFredSeries(id, {
  start = '2022-01-01', end = today(), cacheDir, offline = false,
  fetchImpl = globalThis.fetch, retryDelayMs = 500,
} = {}) {
  assertId(id); assertDate(start, 'start date'); assertDate(end, 'end date');
  if (start > end) throw new Error('start date must not be after end date');
  end = end < today() ? end : today();
  if (start > end) throw new Error('start date must not be in the future');
  if (offline) return readCache(cacheDir, id, start, end);
  if (typeof fetchImpl !== 'function') throw new Error('A Node.js runtime with fetch support is required');
  if (!Number.isFinite(retryDelayMs) || retryDelayMs < 0) throw new Error('retryDelayMs must be nonnegative');
  const url = new URL('https://fred.stlouisfed.org/graph/fredgraph.csv');
  url.search = new URLSearchParams({ id, cosd: start, coed: end }).toString();
  let csv;
  for (let attempt = 0; attempt < 3; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new Error(`FRED request timed out for ${id} after 25 seconds`)), 25_000);
    let retryable = true;
    try {
      const response = await fetchImpl(url.toString(), {
        signal: controller.signal,
        headers: { Accept: 'text/csv', 'User-Agent': 'GeneWorkbookUpdater/1.0' },
      });
      if (!response.ok) {
        retryable = response.status === 408 || response.status === 429 || response.status >= 500;
        throw new Error(`FRED HTTP ${response.status} for ${id}`);
      }
      csv = await response.text();
      break;
    } catch (error) {
      if (!retryable || attempt === 2) throw new Error(`Unable to refresh ${id}: ${error.message}`, { cause: error });
    } finally { clearTimeout(timer); }
    await new Promise(resolve => setTimeout(resolve, retryDelayMs * 2 ** attempt));
  }
  const observations = parseFredCsv(csv, id, end).filter(point => point.date >= start);
  if (!observations.length) throw new Error(`No usable FRED observations for ${id} in ${start} through ${end}`);
  const result = { id, observations, sourceUrl: `https://fred.stlouisfed.org/series/${id}`, fetchedAt: new Date().toISOString() };
  if (cacheDir) await writeCache(cacheDir, id, { ...result, requestedStart: start, requestedEnd: end });
  return result;
}

/** Exact-date lookup. No nearest-date or carry-forward substitutions. */
export function valueAt(series, date) {
  assertDate(date);
  const value = observationMap(series).get(date);
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function latestDate(series) {
  const dates = [...observationMap(series).keys()];
  return dates.length ? dates.reduce((a, b) => a > b ? a : b) : null;
}

/** Latest date actually present in every supplied series, or null if none. */
export function commonLatest(seriesArray) {
  if (!Array.isArray(seriesArray) || !seriesArray.length) return null;
  const maps = seriesArray.map(observationMap);
  const shared = [...maps[0].keys()].filter(date => maps.every(map => Number.isFinite(map.get(date))));
  return shared.length ? shared.reduce((a, b) => a > b ? a : b) : null;
}

/** Growth in percent; e.g. 120/100 gives 20. Negative or zero bases are invalid. */
export function growth(series, date, months, annualized = false) {
  if (!Number.isInteger(months) || months <= 0) throw new Error('Growth months must be a positive integer');
  const current = valueAt(series, date);
  const previous = valueAt(series, monthShift(date, -months));
  if (current === null || previous === null || current < 0 || previous <= 0) return null;
  const result = ((current / previous) ** (annualized ? 12 / months : 1) - 1) * 100;
  return Number.isFinite(result) ? result : null;
}

/** Average monthly level change over an uninterrupted interval (thousands → jobs by default). */
export function averageJobChange(series, end, months, multiplier = 1000) {
  if (!Number.isInteger(months) || months <= 0) throw new Error('Job-change months must be a positive integer');
  if (!Number.isFinite(multiplier)) throw new Error('Job-change multiplier must be finite');
  assertDate(end);
  const map = observationMap(series);
  for (let n = 0; n <= months; n++) {
    const value = map.get(monthShift(end, -n));
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  }
  return (map.get(end) - map.get(monthShift(end, -months))) * multiplier / months;
}

/** Start is the baseline month; changes begin in the following month. */
export function meanJobChangeBetween(series, start, end, multiplier = 1000) {
  assertDate(start, 'start date'); assertDate(end, 'end date');
  const [startYear, startMonth] = start.split('-').map(Number);
  const [endYear, endMonth] = end.split('-').map(Number);
  const months = (endYear - startYear) * 12 + endMonth - startMonth;
  if (months <= 0 || monthShift(end, -months) !== start) return null;
  return averageJobChange(series, end, months, multiplier);
}

export function decemberGrowth(series, year) {
  if (!Number.isInteger(year) || year < 1000 || year > 9999) throw new Error('Invalid year');
  return growth(series, `${year}-12-01`, 12);
}

/** Calendar-year average for monthly first-of-month observations, requiring all 12 months. */
export function yearlyMean(series, year) {
  if (!Number.isInteger(year) || year < 1000 || year > 9999) throw new Error('Invalid year');
  const map = observationMap(series);
  const withinYear = [...map.keys()].filter(date => date.startsWith(`${year}-`));
  // Do not silently treat a daily/weekly series as monthly by sampling day one.
  if (withinYear.length !== 12 || withinYear.some(date => !date.endsWith('-01'))) return null;
  const values = Array.from({ length: 12 }, (_, n) => map.get(`${year}-${String(n + 1).padStart(2, '0')}-01`));
  if (!values.every(value => typeof value === 'number' && Number.isFinite(value))) return null;
  return values.reduce((sum, value) => sum + value, 0) / 12;
}
