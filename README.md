# Economic Briefing — Josh Waldman

[Public dashboard](https://joshfwaldman1.github.io/economic-briefing-updater/) · [Download updater scripts](https://joshfwaldman1.github.io/economic-briefing-updater/downloads/economic-updater-scripts.zip)

U.S. employment, unemployment by race, CPI and PCE inflation, grocery and fuel prices, manufacturing and auto jobs, real GDP, business applications, claims, markets and fiscal data. The dashboard also compares selected indicators with their pre-February 28, 2026 values.

## Automatic website updates

GitHub Actions retrieves current FRED observations **twice daily, at 9:10 a.m. and 7:17 p.m. Eastern time**, then publishes the website. The schedule uses `America/New_York` and follows daylight saving time. The morning check runs on every day, including Jobs Day, after the usual 8:30 a.m. Eastern release. Each run downloads fresh observations and revisions from FRED. FRED may take longer to publish a release, and GitHub may delay a scheduled run; these times are not a guarantee of when new figures will appear. The displayed refresh timestamp changes only after a successful retrieval and deployment. Monthly or quarterly observations change when their source releases new data or revisions, not every time the site refreshes.

The dashboard and its CSV/source-data download refresh automatically. The Word chartbook is a separately dated download; it does not silently inherit the dashboard's newer timestamp. The economic briefing workbook download is currently omitted. Its original updater remains in the repository.

The schedule runs on GitHub, so a personal computer does not need to remain awake. No API key, Codex runtime or paid server is needed for the website refresh. All dashboard arithmetic runs in pandas; the website presents source values and observed changes. The U.S. GDP annual rate is read directly from BEA via FRED. Failed refreshes leave the previously published website in place; inspect [workflow runs](https://github.com/joshfwaldman1/economic-briefing-updater/actions/workflows/pages.yml) for status or use **Run workflow** for an immediate refresh.

## Running the updaters

| Tool | Purpose | Requirements |
| --- | --- | --- |
| `refresh_dashboard.mjs` | Retrieve FRED source series and invoke the pandas builder | Node.js 22+ and Python 3.10+ with pandas |
| `calculate_dashboard.py` | Compute observed changes, totals and averages with pandas | Python 3.10+ and pandas |
| `package_downloads.py` | Package current CSV tables, raw observations and script downloads | Python 3.10+; standard library only |
| `update_chartbook.py` | 34 editable Word tables from 20 seasonally adjusted BLS series | Python 3.10+ and `python-docx` |
| `download_fred_charts.py` | Optional downloads of the four original saved FRED graphs | Python 3.10+; standard library only |
| `update_workbook.mjs` | Refresh the original Excel briefing's mapped economic series | Node.js 20+, Python 3, and the **Codex `@oai/artifact-tool` runtime** |

To refresh the website locally:

```sh
python3 -m pip install -r requirements-dashboard.txt
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

- Employment comparisons use **January 2021 → January 2025** (48 monthly changes), **January 2025 → latest**, and the **total change since January 2021**. January is the level baseline; its own change from December is excluded. Average monthly changes require uninterrupted monthly observations. Payroll employment is displayed in jobs, not unique workers.
- National total auto jobs means **motor vehicle and parts manufacturing + motor vehicle and parts dealers**. It is a defined sum, not an official total of every auto-related occupation. Manufacturing and dealer rows overlap this total. State manufacturing is included; state auto jobs are omitted.
- CPI monthly changes use seasonally adjusted indexes; CPI 12-month changes and the CPI headline use unadjusted indexes, following [BLS reporting](https://www.bls.gov/news.release/cpi.t01.htm). PCE changes use seasonally adjusted indexes. Each CPI row links to both input series. No short-run inflation rates are annualized. Grocery dollar prices, oil, fuel and stock series retain their labeled source conventions.
- **U.S. real GDP** reports BEA's published quarterly growth at an annual rate directly from [A191RL1Q225SBEA](https://fred.stlouisfed.org/series/A191RL1Q225SBEA), alongside the published real GDP level. The dashboard does not compute that annualization. [BEA explains the convention](https://www.bea.gov/help/faq/122): a quarterly annual rate is distinct from growth during a quarter or growth over four quarters.
- **G7 real GDP** shows quarterly growth explicitly **not annualized**, four-quarter changes, and cumulative changes between the labeled endpoints. Every country uses the latest common quarter. Incomparable national-currency levels are omitted. Q1 baselines are full-quarter observations, not January-only values or exact presidential-term boundaries.
- The **Since Iran War began** tab uses the user-selected February 28, 2026 start. Daily and weekly baselines are the last available observation before that date. Monthly indicators use January 2026, the last full prewar month. Actual dates appear beside the values. These are descriptive changes, not estimates of the war's causal effect.
- WTI and Brent use [EIA spot prices](https://www.eia.gov/dnav/pet/PET_PRI_SPT_S1_D.htm) via FRED. Daily observation frequency does not mean live quotes or daily publication. The latest observation date can precede the dashboard refresh date because the source publishes with a delay; futures prices are a different instrument.
- Hispanic ethnicity overlaps racial classifications. Industry subsets overlap their parent totals. Do not sum overlapping rows.
- Categories without a configured source series are omitted. Missing observations within supported series stay unavailable. Current revisions are downloaded; this is not a historical-vintage service. A source failure stops automatic publication rather than relabeling cached data as fresh.
- AAA daily prices, the release calendar and three PCE component rows in the original workbook remain explicitly manual. Those workbook values are not carried into the live dashboard as updated data.
- Source data remain subject to their providers' terms. The four original custom FRED graph links appear at the bottom of the website.

## Tests and publication

```sh
node --test test-data.mjs test-workbook.mjs test-dashboard.mjs
python3 -m unittest test_chartbook.py test_calculate_dashboard.py test_validate_calculations.py
python3 validate_dashboard.py
```

Pandas tests cover observed changes, missing observations, payroll scaling, comparison-period denominators, derived totals and prewar baselines. An independent pandas validator recomputes the displayed figures from the archived raw observations before publication. It also checks official U.S. GDP rates against GDP levels at the published precision, and verifies CPI's separate SA and NSA inputs. Node.js tests cover source transport, failures and snapshot integrity. GitHub Actions validates before deploying. The deployment job explicitly publishes the scheduled refresh; it does not rely on a bot commit triggering another workflow.
