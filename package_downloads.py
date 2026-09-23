#!/usr/bin/env python3
"""Package refreshed dashboard CSV tables and portable updater source files.

Python standard library only. The Word chartbook remains separately dated.
This prepares local files; GitHub Actions handles publishing.
"""
from pathlib import Path
from datetime import datetime
import argparse
import csv
import io
import json
import zipfile

ROOT = Path(__file__).resolve().parent
DOCUMENTS = [
    {'path': 'downloads/labor-market-chartbook.docx', 'label': 'BLS labor market chartbook',
     'description': '34 editable tables · DOCX · run the BLS updater to refresh', 'updatedAt': '2026-09-23'},
]


def package(output_dir):
    data_path = output_dir / 'data.json'
    data = json.loads(data_path.read_text())
    timestamp = data['retrievedAt']
    datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    downloads = output_dir / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    series = json.loads((output_dir / 'series.json').read_text())
    if series['retrievedAt'] != timestamp or series.get('snapshotId') != data.get('snapshotId'):
        raise ValueError('Dashboard and raw series retrieval timestamps differ')
    with zipfile.ZipFile(downloads / 'dashboard-data.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        notes = [f'Economic Briefing — Josh Waldman\nRefreshed: {timestamp}\n',
                 'Each CSV contains the displayed table, its units and source links. Nulls mean unavailable.\n',
                 'series.json contains source observations in their ORIGINAL source units.\n',
                 'Totals and averages use the exact baseline periods described below.\n']
        for section in data['sections']:
            buffer = io.StringIO(newline='')
            writer = csv.writer(buffer)
            writer.writerow([c['label'] for c in section['columns']] + ['Source links'])
            for row in section['rows']:
                sources = row.get('sources') or []
                urls = [s['url'] for s in sources] or [row.get('source') or '']
                writer.writerow(row['values'] + [' | '.join(urls)])
            archive.writestr(section['key'] + '.csv', buffer.getvalue())
            notes.append(f"\n{section['title']}\n{section.get('note', '')}\n{section.get('sourceNote', '')}\n")
        archive.writestr('README.txt', ''.join(notes))
        archive.write(output_dir / 'series.json', 'series.json')
    data['downloads'] = [
        {'path': 'downloads/dashboard-data.zip', 'label': 'Current dashboard tables and source data',
         'description': 'All indicator tables as CSV + source observations as JSON', 'updatedAt': timestamp},
        *DOCUMENTS,
    ]
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    with zipfile.ZipFile(downloads / 'economic-updater-scripts.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.iterdir()):
            if path.is_file() and path.suffix in {'.mjs', '.py', '.json', '.md', '.txt', '.command', '.xlsx'}:
                archive.write(path, Path('economic-updater') / path.name)
        for name in ['index.html', 'style.css', 'app.js', '.nojekyll']:
            archive.write(output_dir / name, Path('economic-updater/docs') / name)
        for path in sorted((ROOT / '.github/workflows').glob('*.yml')):
            archive.write(path, Path('economic-updater/.github/workflows') / path.name)
        archive.write(ROOT / '.gitignore', 'economic-updater/.gitignore')
    print(f'Packaged {len(data["sections"])} current tables and updater source.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'docs')
    package(parser.parse_args().output_dir)
