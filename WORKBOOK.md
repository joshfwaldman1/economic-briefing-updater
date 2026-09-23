# Economic briefing updater

This folder contains reusable scripts for the Gene Master Prep workbook, the BLS chart book, and your four saved FRED graphs. Source files are never overwritten.

Double-click **Update Everything.command** on this Mac to run all three updaters into one dated folder under `runs/`. You can also use the separate workbook and chartbook launchers. No recurring schedule is installed.

## Update the workbook

On a Mac with the Codex workspace runtime installed, double-click **Update Workbook.command**. It finds the bundled Codex Node runtime, downloads current FRED observations, and creates a dated workbook and refresh report in `runs/`. The included `template.xlsx` is a copy of your supplied workbook.

From Terminal:

```bash
./Update\ Workbook.command
```

To refresh a workbook that you have edited yourself, give its path:

```bash
./Update\ Workbook.command --input "/path/to/your workbook.xlsx" --output "/path/to/new workbook.xlsx"
```

The output must be a new `.xlsx` filename. Download failures are written to the refresh log and displayed as unavailable, never zero. Add `--strict` to prevent any workbook output when a series download fails. `--offline` uses an existing complete cache explicitly and labels the workbook as cached. `--as-of 2026-09-23` caps observation dates but uses today's revised history; it does not reproduce a historical data vintage.

The JavaScript updater requires Node 20+ and `@oai/artifact-tool`. It finds that package in an installed Codex runtime automatically. For another machine, use a Codex environment with the workspace dependencies available or set `ARTIFACT_TOOL_ROOT` to the Node dependency directory. The data and graph downloader modules otherwise use standard runtime libraries. No FRED API key is required.

Python 3 is also used for a small standard-library repair that keeps source hyperlinks attached to the correct rows after the employment table expands. It is found in the bundled runtime automatically, or can be set with `GENE_PYTHON`. The Word updater needs `python-docx`, which can be installed from requirements.txt; see its README.

## Coverage

The workbook refreshes CPI, mapped PCE components, EIA weekly fuels, employment by major industry and selected subsets, nominal and calculated real hourly earnings, prime-age participation and employment, unemployment by race, consumer sentiment, selected goods price indexes, selected state and auto manufacturing payrolls, business applications, claims, stock indexes, and federal deficits.

Added industries include construction, health care, leisure and hospitality, retail, professional and business services, government, mining and logging, information, financial activities, private education and health, other services, wholesale, transportation and warehousing, and utilities. Overall and overlapping subsets are labeled and are not summed together.

Unemployment includes overall, prime age, men, women, White, Black or African American, Hispanic or Latino, and Asian. Those series use published seasonally adjusted data. Hispanic ethnicity can be of any race, so those rows are not mutually exclusive. Business applications include total and high-propensity applications; high propensity is a subset, and applications are not realized business formations.

Additional context includes JOLTS job openings, the quits rate, U-6 underemployment, and the prime-age employment-to-population ratio. NFP is the Overall payroll row (`PAYEMS`). Stocks are the S&P 500, Dow Jones Industrial Average, and NASDAQ Composite, with price changes excluding dividends. Market prices, fuel prices, consumer sentiment and Treasury cash budget data remain in their published, non-seasonally-adjusted form.

The Refresh Log gives each mapped series, source link, units, adjustment status, latest observation and refresh status. Data can be revised. A recent retrieval is not a guarantee of a recent observation; lagged series are flagged. Each sheet displays its actual observation dates.

## Manual sections

AAA daily fuel prices, the release calendar, and the three unverified PCE components (core goods, core services, housing) remain clearly marked **manual / not refreshed**. The script retains their supplied values and does not substitute a different economic measure. EIA weekly prices are refreshed separately from AAA. Michigan sentiment through FRED has a source-imposed publication delay.

The G7 tab retains the original graph reference and points to the custom graph downloader. Use the supplied G7 saved graph in that downloader. Its raw national GDP series have different units, so do not compare raw GDP levels across countries as a ranking of real output.

## Calculation conventions

- Payroll source levels are thousands of people. Monthly differences and their averages are multiplied by 1,000 for the workbook's job counts. Full exact monthly histories are required for averages.
- `termBaseline` in `config.json` defaults to January 2025. The term average includes monthly changes from February 2025 through the latest observation. Change the baseline to December 2024 if you want January 2025's change included.
- Inflation uses index ratios. Annualized growth over `n` months is `100 × ((index_t / index_t-n)^(12/n) − 1)`. YoY uses a 12-month ratio. All mapped CPI/PCE calculations use SA levels, so calculated CPI YoY may differ slightly from the headline NSA convention in a release. The 2023 and 2024 columns mean December-to-December growth.
- Percentages are stored as percentage points (for example, `2.5` means 2.5%). Rate differences are percentage points. Missing values are `n.a.` and genuine zero values remain zero.
- Real hourly earnings are nominal all-private hourly earnings divided by CPI-U and multiplied by 100, aligned to exactly matching months.
- EIA comparisons use exactly 1, 4 and 52 weeks earlier. Annual EIA figures are explicitly labeled means of weekly observations, not official annual aggregates.
- Treasury source balances are in millions of dollars with negative deficits. The displayed deficit reverses the sign and converts to billions. Fiscal year to date starts in October. Trailing totals require every month; the script does not annualize a single monthly balance.
- Market lookbacks use the last available close on or before the calendar comparison date, within seven days. No interpolation is used.

## Add an industry

Edit `config.json` and append an item to `employment`, using a verified monthly seasonally adjusted FRED payroll series in thousands of persons:

```json
{"id": "USCONS", "label": "Construction", "kind": "major_industry", "sa": "SA", "frequency": "Monthly", "units": "Thousands of persons"}
```

That example is already included; do not add it twice. A subset also needs `"kind": "subset"`, an `overlaps_with` parent series, and a clear label. The script rejects duplicate series IDs within a group. Other groups follow the same configuration pattern, but their calculations depend on the group's units and frequency. Verify metadata before adding a series.

## Update the custom FRED graphs

```bash
python3 download_fred_charts.py --help
python3 download_fred_charts.py
```

`fred_graphs.json` stores the four supplied saved-graph URLs. The downloader uses the saved graph's own CSV export, retaining transformations such as the inflation graph's year-over-year changes. Source metadata accompanies the files. It does not replace your custom graph with an assumed series list.

Native PNG charts are downloaded alongside the CSVs. Use `--csv-only` to skip image downloads. Downloaded files and per-graph metadata are in `fred_charts/` by default.

## Update the Word chart book

See **README_chartbook.md** for the direct BLS updater and its options. The 2022 source contains static table images; the updater recreates the same subjects as editable month-by-year tables using published seasonally adjusted BLS series, including Hispanic men and women age 20 and over.

## Tests

```bash
node --test test-data.mjs test-workbook.mjs
```

Tests cover exact calendar periods, missing data, annualization, payroll scaling, parsing, retries, and explicit offline caches. The initial published workbook was also checked against the original for source-table preservation and visually reviewed. Scripts fetch current revised data on each run; they do not install a schedule.
