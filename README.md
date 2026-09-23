# Economic Briefing — Josh Waldman

[Public dashboard](https://joshfwaldman1.github.io/economic-briefing-updater/) · [Download updater scripts](https://joshfwaldman1.github.io/economic-briefing-updater/downloads/economic-updater-scripts.zip)

U.S. employment, unemployment by race, CPI and PCE inflation, grocery and fuel prices, manufacturing and auto jobs, real GDP, business applications, claims, markets and fiscal data. The dashboard also compares selected indicators with their pre-February 28, 2026 values.

## Automatic website updates

GitHub Actions retrieves current FRED observations **twice daily, at 14:17 and 23:17 UTC**, then publishes the website. These are scheduled times; GitHub may delay a run. The displayed refresh timestamp changes only after a successful retrieval and deployment. Monthly or quarterly observations change when their source releases new data or revisions, not every time the site refreshes.

The dashboard and its CSV/source-data download refresh automatically. The Word chartbook is a separately dated download; it does not silently inherit the dashboard's newer timestamp. The economic briefing workbook download is currently omitted. Its original updater remains in the repository.

The schedule runs on GitHub, so a personal computer does not need to remain awake. No API key, Codex runtime or paid server is needed for the website refresh. Failed refreshes leave the previously published website in place; inspect [workflow runs](https://github.com/joshfwaldman1/economic-briefing-updater/actions/workflows/pages.yml) for status or use **Run workflow** for an immediate refresh.

## Running the updaters

| Tool | Purpose | Requirements |
| --- | --- | --- |
| `refresh_dashboard.mjs` | Retrieve source series and build all website indicator tables | Node.js 22+; built-in modules only |
| `package_downloads.py` | Package current CSV tables, raw observations and script downloads | Python 3.10+; standard library only |
| `update_chartbook.py` | 34 editable Word tables from 20 seasonally adjusted BLS series | Python 3.10+ and `python-docx` |
| `download_fred_charts.py` | Optional downloads of the four original saved FRED graphs | Python 3.10+; standard library only |
| `update_workbook.mjs` | Refresh the original Excel briefing's mapped economic series | Node.js 20+, Python 3, and the **Codex `@oai/artifact-tool` runtime** |

To refresh the website locally:

```sh
node refresh_dashboard.mjs
python3 package_downloads.py
python3 validate_dashboard.py
python3 -m http.server 8765 --directory docs
```

Review the local site, commit the updated files and push to `main`. The Pages workflow publishes `docs/` on pushes and on scheduled/manual refreshes. `docs/data.json` contains the displayed tables; `docs/series.json` preserves original source observations, units and retrieval timestamps. The dashboard data ZIP contains all table CSVs plus those original observations.

To refresh the Word chartbook or download the original saved graphs:

```sh
python3 -m pip install -r requirements.txt
python3 update_chartbook.py --output-dir runs/chartbook
python3 download_fred_charts.py --output-dir runs/fred_charts
```

**The original Excel updater requires the Codex spreadsheet runtime.** Ordinary Node.js alone is insufficient. It locates that runtime automatically when available or accepts its dependency directory in `ARTIFACT_TOOL_ROOT`:

```sh
node update_workbook.mjs --output runs/briefing.xlsx
```

The Mac `.command` launchers operate the original workbook/chartbook tools. They do not publish the website. See [workbook instructions](WORKBOOK.md) and [chartbook instructions](README_chartbook.md) for configuration. Never commit API keys or generated private local reports.

## Definitions and coverage

- Employment comparisons use **January 2021 → January 2025** (48 monthly changes), **January 2025 → latest**, and the **total change since January 2021**. January is the level baseline; its own change from December is excluded. Average monthly changes require uninterrupted monthly observations. Employment is displayed in people.
- National total auto jobs means **motor vehicle and parts manufacturing + motor vehicle and parts dealers**. It is a defined sum, not an official total of every auto-related occupation. Manufacturing and dealer rows overlap this total. State manufacturing is included; state auto jobs are omitted.
- CPI and PCE growth use seasonally adjusted indexes. Grocery dollar prices, oil, fuel and stock series retain their published adjustment conventions, which are labeled. A pound of beef is a dollar price per pound, not a price index.
- GDP observations retain their own national units. Growth rates can be compared across countries; their raw national levels cannot be added or ranked as common-dollar GDP.
- The **Since Iran War began** tab uses the user-selected February 28, 2026 start. Daily and weekly baselines are the last available observation before that date. Monthly indicators use January 2026, the last full prewar month. Actual dates appear beside the values. These are descriptive changes, not estimates of the war's causal effect.
- Hispanic ethnicity overlaps racial classifications. Industry subsets overlap their parent totals. Do not sum overlapping rows.
- Missing observations stay unavailable. Current revisions are downloaded; this is not a historical-vintage service. A source failure stops automatic publication rather than relabeling cached data as fresh.
- AAA daily prices, the release calendar and three PCE component rows in the original workbook remain explicitly manual. Those workbook values are not carried into the live dashboard as updated data.
- Source data remain subject to their providers' terms. The four original custom FRED graph links appear at the bottom of the website.

## Tests and publication

```sh
node --test test-data.mjs test-workbook.mjs test-dashboard.mjs
python3 -m unittest test_chartbook.py
python3 validate_dashboard.py
```

Tests cover calendar lags, missing observations, payroll scaling, comparison-period denominators, derived totals, prewar baselines, CSV validation, retries and source protection. GitHub Actions validates before deploying. The deployment job explicitly publishes the scheduled refresh; it does not rely on a bot commit triggering another workflow.
