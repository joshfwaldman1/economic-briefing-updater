# BLS chartbook updater

`update_chartbook.py` refreshes all 34 year-by-month tables in the supplied labor-market chartbook. It replaces the old pictures with editable Word tables, retaining the original subjects and sequence. It downloads revised history from the BLS public API, recalculates monthly and 12-month changes, and writes a separate DOCX.

Requires Python 3.10+ and `python-docx`:

```sh
python3 -m pip install python-docx
python3 update_chartbook.py --output-dir ../chartbook
```

To associate the update with the original document and reuse its styles:

```sh
python3 update_chartbook.py \
  --input "/path/to/charts book.docx" \
  --output-dir ../chartbook
```

The original file is never modified. Use a new output directory for each run, or add `--overwrite` to replace earlier generated outputs. Input and output directories must be different.

## Coverage

- Nonfarm payrolls, manufacturing, motor vehicles and parts manufacturing, and auto manufacturing plus dealers.
- State plus local government and their education employment.
- Total and women's civilian labor force levels and changes.
- Overall unemployment, overall and prime-age participation.
- Black and Hispanic unemployment overall and for men and women age 20 and over.
- Youth unemployment ages 16 to 24.

`chartbook_config.json` contains every BLS ID, source URL, unit, seasonal adjustment, calculation, and table definition. Additional industries or demographics can be added there. Sum only series with matching units and seasonal adjustment and without overlapping populations. A DOCX supplied through `--input` must be the original 34-image chartbook; omit `--input` for a new configuration.

## Options

```sh
# Display the last ten calendar years through the current year
python3 update_chartbook.py --years 10 --output-dir ../chartbook-10-years

# Display history from 2015 through an observation cutoff
python3 update_chartbook.py --start-year 2015 --as-of 2026-08 --output-dir ../chartbook-august

# Rebuild from an explicit saved snapshot without downloading again
python3 update_chartbook.py --offline-data ../chartbook/observations.json \
  --output-dir ../chartbook-rebuilt
```

The default display begins in 2009. One additional year is fetched for lag calculations. BLS requests are split into at most 25 series and 10 calendar years, so no API key is required for the standard run. Set `BLS_API_KEY` in the environment to use your registered key; keys are never saved in the output. BLS daily request limits still apply. A cutoff filters observation months using the latest published revision; it does **not** recreate the information available on a past date.

The script fails before writing a DOCX if a required series is unavailable. It does not silently reuse cached data. `--allow-fred-fallback` explicitly permits a fallback to FRED's BLS mirror when a BLS request fails or returns no observations. Every fallback is printed, logged in the manifest, and labeled in the document; FRED does not provide BLS preliminary point footnotes. Default behavior uses BLS only. Hispanic men and women age 20 and over have no verified FRED mirror in this configuration, so their retrieval requires BLS even when fallback is enabled.

## Outputs

- `Labor Market Chartbook Updated.docx`: 34 refreshed, editable tables, actual observation dates, units and source IDs.
- `observations.json` and `observations.csv`: downloaded observations, source providers and full BLS footnotes.
- `tables.csv`: the calculated values used in the document.
- `manifest.json`: retrieval time, configuration hash, original document hash when supplied, series metadata, latest observations, missing months, fallback events and output hash.
- `raw/`: original BLS API responses or explicitly permitted FRED CSV responses.

A dash marks an unavailable historical observation or missing comparison month; later months after the series' latest observation are blank. Values are never interpolated or replaced with zero. An asterisk marks preliminary values and changes that use them. Totals use dates available for every component. Month-over-month and 12-month changes use exact calendar offsets, not the previous available row.

All series are seasonally adjusted, including Hispanic men and women age 20 and over (BLS LNS14000034 and LNS14000035). Changes in CPS labor force levels can include January population-control revisions; these are differences in the published levels, not break-adjusted economic changes. Auto total means motor vehicles and parts manufacturing plus motor vehicle and parts dealers, not the complete automotive supply chain.

All 34 original tables are represented, but the DOCX is rebuilt to remove obsolete 2022 images and the old cached contents page. Editable tables use consistent widths, repeat column headers when needed, and split long histories into 18-year panels. The source document is treated solely as data and a visual reference.

## Validation

```sh
python3 -m unittest test_chartbook.py
```

Tests cover exact calendar lags, missing-month gaps, component intersections, exclusion of annual averages, preliminary flags, and API failures. Open each new DOCX to review its layout after changing the configuration or display window. The delivered sample was rendered and all pages were visually checked using the bundled document renderer.

Primary documentation: [BLS API](https://www.bls.gov/developers/api_signature_v2.htm), [CPS documentation](https://www.bls.gov/cps/documentation.htm). Each mapping also includes its BLS series link and primary metadata verification link.
