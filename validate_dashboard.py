#!/usr/bin/env python3
"""Validate dashboard files and independently audit calculations with pandas."""
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import argparse
import json
import math
import zipfile
from validate_calculations import validate_calculations


def validate(root):
    data = json.loads((root / 'data.json').read_text())
    raw = json.loads((root / 'series.json').read_text())
    assert data['retrievedAt'] == raw['retrievedAt'], 'Mismatched data timestamps'
    assert data.get('snapshotId') and data['snapshotId'] == raw.get('snapshotId'), 'Mismatched snapshot IDs'
    stamp = datetime.fromisoformat(data['retrievedAt'].replace('Z', '+00:00'))
    assert stamp.tzinfo and stamp <= datetime.now(timezone.utc), 'Invalid refresh timestamp'
    assert len(data['kpis']) == 3, 'Expected payroll, unemployment and CPI headlines'
    assert all(k.get('source', '').startswith('https://fred.stlouisfed.org/') for k in data['kpis'])
    assert len(data['sections']) >= 12, 'Missing indicator groups'
    keys = [s['key'] for s in data['sections']]
    assert len(keys) == len(set(keys)), 'Duplicate table keys'
    for section in data['sections']:
        assert section['rows'] and section['columns'], section['key']
        for row in section['rows']:
            assert len(row['values']) == len(section['columns']), section['key']
            for value in row['values']:
                if isinstance(value, (int, float)):
                    assert math.isfinite(value), f'Invalid number in {section["key"]}'
            for link in ([row['source']] if row.get('source') else []) + [s['url'] for s in row.get('sources', [])]:
                assert link.startswith('https://fred.stlouisfed.org/'), link
    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if key not in ('src', 'href') or not value or value.startswith(('https:', 'http:', 'data:', '#')):
                    continue
                assert (root / value.split('#')[0]).exists(), value
    Links().feed((root / 'index.html').read_text())
    for item in data.get('downloads', []):
        assert (root / item['path']).exists(), item['path']
    for name in ['economic-updater-scripts.zip', 'dashboard-data.zip']:
        with zipfile.ZipFile(root / 'downloads' / name) as archive:
            assert archive.testzip() is None, name
    validate_calculations(root)
    print(f'Validated {len(data["sections"])} tables, {len(raw["series"])} source series, dates, links and archives.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'docs')
    validate(parser.parse_args().output_dir)
