# Economic Briefing Updater

[Public dashboard](https://joshfwaldman1.github.io/economic-briefing-updater/) · [Download scripts](https://joshfwaldman1.github.io/economic-briefing-updater/downloads/economic-updater-scripts.zip)

An economic briefing workbook, a BLS labor-market chartbook, and downloads of four saved FRED graphs. The public dashboard displays an explicitly dated snapshot with employment, unemployment by race, inflation, business applications, jobless claims, stock indexes and federal deficits.

## Running the updaters

There are three independent tools:

| Tool | Purpose | Requirements |
| --- | --- | --- |
| `update_chartbook.py` | 34 editable Word tables from 20 direct, seasonally adjusted BLS series | Python 3.10+ and `python-docx` |
| `download_fred_charts.py` | Saved FRED graphs as CSV and PNG, preserving transformations | Python 3.10+; standard library only |
| `update_workbook.mjs` | Refresh 67 mapped economic series and 17 employment categories in Excel | Node.js 20+, Python 3, and the **Codex `@oai/artifact-tool` workspace runtime** |

**The Excel updater is not a standalone npm package.** Ordinary Node.js alone is insufficient. It locates the Codex spreadsheet runtime automatically when available, or accepts its dependency directory in `ARTIFACT_TOOL_ROOT`. The Python chartbook and graph tools can run independently on ordinary machines.

```sh
python3 -m pip install -r requirements.txt
python3 update_chartbook.py --output-dir runs/chartbook
python3 download_fred_charts.py --output-dir runs/fred_charts
```

In a configured Codex workspace:

```sh
node update_workbook.mjs --output runs/briefing.xlsx
```

On a Mac with that runtime installed, `Update Everything.command` runs all three tools into a dated folder. The individual `.command` launchers run just the workbook or chartbook. No recurring schedule is installed.

See [workbook instructions](WORKBOOK.md) and [chartbook instructions](README_chartbook.md) for configuration, calculation definitions, missing-data behavior and optional API-key settings. Never commit API keys or generated local reports.

## Data coverage and limits

- Labor series use published seasonal adjustment. Hispanic ethnicity overlaps racial classifications; industry subsets overlap their parent totals.
- Stock indexes, Treasury cash budget balances and weekly EIA fuel prices retain their published NSA conventions. Stock changes exclude dividends.
- AAA daily prices, the release calendar, and PCE core goods, core services and housing remain explicitly marked for manual updates.
- The included workbook template contains supplied historical values in those manual sections. They are not updated automatically.
- Current revisions are downloaded. An observation cutoff is not a historical vintage. Missing values stay unavailable and do not become zeros.
- The original G7 graph uses national GDP levels with different units; use normalized growth for cross-country comparisons.
- Source data and original FRED chart attribution remain subject to their respective providers' terms. Public visibility of this repository does not change those terms.

## Publish a new dashboard snapshot

The site is static HTML, CSS and JavaScript in `docs/`, hosted by GitHub Pages. It has no backend, login, tracking, secret keys or runtime API requests. The current site is a snapshot, not a live feed.

After running the updaters, build the public snapshot locally:

```sh
python3 publish_snapshot.py \
  --workbook runs/briefing.xlsx \
  --chartbook "runs/chartbook/Labor Market Chartbook Updated.docx" \
  --charts runs/fred_charts \
  --retrieved YYYY-MM-DD
```

Use the actual retrieval date. This copies the selected workbook and chartbook into the public downloads, exports dashboard values, copies four chart PNG/CSV pairs, and rebuilds the scripts ZIP. It does not upload anything. Review the output, commit and push to `main`; Pages publishes `docs/` automatically.

## Tests

```sh
node --test test-data.mjs test-workbook.mjs
python3 -m unittest test_chartbook.py
```

The calculation tests cover exact calendar lags, missing observations, payroll scaling, annualization, CSV validation, retries, cache handling and source-file protection. GitHub Actions runs these tests on pushes and pull requests. The public page and downloads were also checked before publication.
