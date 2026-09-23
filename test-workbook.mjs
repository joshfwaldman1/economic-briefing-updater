import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { parseArgs, main } from './update_workbook.mjs';

test('CLI accepts paths with spaces and deliberate offline/strict mode', () => {
  assert.deepEqual(parseArgs([
    '--input', '/tmp/Gene Master Prep Doc.xlsx', '--output', '/tmp/Gene updated.xlsx',
    '--as-of', '2026-09-23', '--offline', '--strict', '--render-dir', '/tmp/previews',
  ]), {
    input: '/tmp/Gene Master Prep Doc.xlsx', output: '/tmp/Gene updated.xlsx',
    'as-of': '2026-09-23', offline: true, strict: true, 'render-dir': '/tmp/previews',
  });
});

test('CLI catches typo flags and absent values rather than silently proceeding', () => {
  assert.throws(() => parseArgs(['--offine']), /Unknown option/);
  assert.throws(() => parseArgs(['--output']), /Missing value/);
  assert.throws(() => parseArgs(['--input', '--offline']), /Missing value/);
  assert.throws(() => parseArgs(['file.xlsx']), /Unknown option/);
});

test('invalid observation cutoff dates fail before any output or network activity', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'gene-cli-test-'));
  try {
    const config = join(dir, 'config.json');
    await writeFile(config, '{}');
    for (const date of ['2026-02-30', '2026-13-01', 'September 23, 2026']) {
      await assert.rejects(main(['--config', config, '--as-of', date, '--output', join(dir, 'result.xlsx')]), /Invalid --as-of/);
    }
    assert.deepEqual(await readdir(dir), ['config.json']);
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('input and existing output files are never replaced', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'gene-cli-test-'));
  try {
    const config = join(dir, 'config.json');
    const input = join(dir, 'original.xlsx');
    const output = join(dir, 'result.xlsx');
    await writeFile(config, '{}');
    await writeFile(input, 'original workbook sentinel');
    await writeFile(output, 'existing output sentinel');
    await assert.rejects(main(['--config', config, '--input', input, '--output', input]), /Input and output must differ/);
    await assert.rejects(main(['--config', config, '--input', input, '--output', output]), /already exists/);
    assert.equal(await readFile(input, 'utf8'), 'original workbook sentinel');
    assert.equal(await readFile(output, 'utf8'), 'existing output sentinel');
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('an existing refresh report prevents creation of an orphaned workbook', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'gene-cli-test-'));
  try {
    const config = join(dir, 'config.json');
    const input = join(dir, 'original.xlsx');
    const output = join(dir, 'result.xlsx');
    const report = join(dir, 'result.refresh.json');
    await writeFile(config, '{}');
    await writeFile(input, 'original workbook sentinel');
    await writeFile(report, 'existing report sentinel');
    await assert.rejects(main(['--config', config, '--input', input, '--output', output]), /already exists/);
    assert.equal(await readFile(report, 'utf8'), 'existing report sentinel');
    assert.ok(!(await readdir(dir)).includes('result.xlsx'));
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('invalid term-baseline calendar months fail before downloads', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'gene-cli-test-'));
  try {
    const config = join(dir, 'config.json');
    const input = join(dir, 'original.xlsx');
    await writeFile(input, 'original workbook sentinel');
    await writeFile(config, JSON.stringify({termBaseline:'2025-99-01'}));
    await assert.rejects(main(['--config', config, '--input', input, '--output', join(dir, 'result.xlsx')]), /valid first-of-month/);
    assert.ok(!(await readdir(dir)).includes('result.xlsx'));
  } finally { await rm(dir, { recursive: true, force: true }); }
});
