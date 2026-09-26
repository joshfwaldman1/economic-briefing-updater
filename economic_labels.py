"""Plain economic terminology for dashboard tables.

This helper changes presentation text only. It does not calculate, format or
replace observations, and does not add/remove/reorder rows or columns.
"""
from __future__ import annotations


EMPLOYMENT_COLUMNS = {
    'Total jobs': 'Employment level (jobs)',
    'Monthly change': '1-month change (jobs)',
    '3-month avg.': '3-month avg. (jobs/month)',
    '12-month avg.': '12-month avg. (jobs/month)',
    'Jan 2021–Jan 2025 total': 'Jan 2021–Jan 2025 net change (jobs)',
    'Jan 2021–Jan 2025 monthly avg.': 'Jan 2021–Jan 2025 avg. (jobs/month)',
    'Since Jan 2025 total': 'Since Jan 2025 net change (jobs)',
    'Since Jan 2025 monthly avg.': 'Since Jan 2025 avg. (jobs/month)',
    'Since Jan 2021 total': 'Since Jan 2021 net change (jobs)',
    'Period': 'Latest month',
}


def _rename_columns(section, names):
    for column in section.get('columns', []):
        if column.get('label') in names:
            column['label'] = names[column['label']]


def apply_economic_labels(sections):
    """Mutate labels/notes only, returning the same section list for convenience.

    Matching existing header text makes the helper compatible with the industry
    table without an employment-level column and with the manufacturing table
    that retains that column. Unknown sections and GDP sections are untouched.
    """
    for section in sections:
        key = section.get('key')
        if key in ('employment', 'manufacturing'):
            _rename_columns(section, EMPLOYMENT_COLUMNS)
            section['note'] = (
                'Payroll jobs, seasonally adjusted. Net change is the ending level minus the starting level for the stated period. '
                '“Since” comparisons end in the latest month shown. Jan 2021–Jan 2025 compares those two January levels. '
                'Monthly averages summarize observed job changes over the stated period; they are not forecasts. '
                'Averages require every month in the period. Subsets overlap their parent industries.'
            )
            if key == 'employment':
                section['title'] = 'Payroll employment by industry'
                section['sourceNote'] = (
                    'Source: BLS Current Employment Statistics via FRED. Employment counts payroll jobs, not unique workers. '
                    'Changes use the current revised data; missing observations remain unavailable.'
                )
            else:
                section['title'] = 'Manufacturing and auto employment'
                section['note'] += (
                    ' The defined auto total combines motor vehicles and parts manufacturing with motor vehicle and parts dealers. '
                    'It excludes auto repair, wholesale and other auto-related industries.'
                )
                section['sourceNote'] = (
                    'Source: BLS Current Employment Statistics via FRED. Component totals use dates available in every source. '
                    'Michigan, Ohio, Wisconsin, Pennsylvania and Minnesota are selected states, not a complete region.'
                )

        elif key in ('unemployment', 'participation'):
            _rename_columns(section, {
                '1m change (pp)': '1-month change (percentage points)',
                '1y change (pp)': '12-month change (percentage points)',
                'Period': 'Latest month',
            })
            if key == 'unemployment':
                _rename_columns(section, {'Rate (%)': 'Unemployment rate (%)'})
                section['title'] = 'Unemployment rates by demographic group'
                section['note'] = (
                    'Seasonally adjusted. Unemployment rates measure unemployed people as a share of the labor force. '
                    'Ages 16 and over unless stated otherwise. Hispanic or Latino is an ethnicity and may overlap any race. '
                    'Changes in rates are percentage points.'
                )
            else:
                section['title'] = 'Prime-age labor force participation and employment'
                section['note'] = (
                    'People ages 25–54, seasonally adjusted. Labor force participation is the share of the population '
                    'working or actively seeking work. The employment-to-population ratio is the share employed. '
                    'Changes in either rate are percentage points.'
                )
            section['sourceNote'] = 'Source: BLS Current Population Survey via FRED. Comparison months must be present in the source data.'

        elif key == 'inflation':
            _rename_columns(section, {
                'MoM (%)': '1-month change (%, SA)',
                '1-month change (%)': '1-month change (%, SA)',
                'YoY (%)': '12-month change (%)',
                'Period': 'Latest month',
                '12m adjustment': '12-month adjustment',
                'Year-over-year adjustment': '12-month adjustment',
            })
            section['title'] = 'Consumer price inflation: CPI and PCE'
            has_adjustment_column = any(column.get('label') == '12-month adjustment' for column in section.get('columns', []))
            section['note'] = (
                'Percent changes in price indexes. The 1-month change is seasonally adjusted (SA). '
                'CPI and PCE measure different baskets of consumer spending; core measures exclude food and energy.'
            )
            if has_adjustment_column:
                section['note'] += ' CPI 12-month changes are not seasonally adjusted (NSA); PCE 12-month changes use SA indexes, as indicated.'
            else:
                section['note'] += ' The 12-month figures here also use SA indexes and can differ slightly from published NSA CPI 12-month changes.'
            section['sourceNote'] = 'Sources: BLS Consumer Price Index and BEA Personal Consumption Expenditures Price Index via FRED. All changes compare observed index values.'

        elif key == 'prices':
            _rename_columns(section, {
                'Latest price ($)': 'Price ($)',
                'YoY (%)': '12-month change (%)',
                'Unit': 'Price unit',
                'Period': 'Latest observation',
            })
            section['title'] = 'Retail prices: gasoline and basic goods'
            section['note'] = (
                'Dollar prices for the stated quantity. The prior period is the preceding month for goods and the '
                'preceding week for fuel. Twelve-month comparisons use the same month a year earlier, or 52 weeks '
                'earlier for weekly fuel prices. Published adjustment is shown for each series.'
            )
            section['sourceNote'] = (
                'Sources: BLS U.S. city average retail prices and EIA U.S. retail fuel prices via FRED. '
                'Average retail prices describe dollar costs; CPI and PCE indexes are the measures of inflation.'
            )

        elif key == 'applications':
            _rename_columns(section, {
                'Applications': 'Application category',
                'Level': 'Applications (count)',
                'MoM (%)': '1-month change (%)',
                'YoY (%)': '12-month change (%)',
                'Period': 'Latest month',
            })
            section['title'] = 'Business applications'
            section['note'] = (
                'Monthly application counts, seasonally adjusted. Applications are not counts of businesses opened. '
                'High-propensity applications are a subset of total applications with characteristics associated with '
                'a higher likelihood of becoming an employer business.'
            )
            section['sourceNote'] = 'Source: U.S. Census Bureau Business Formation Statistics via FRED. Changes compare observed monthly counts.'

        elif key == 'claims':
            _rename_columns(section, {
                'Claims': 'Latest claims (level)',
                '1 week ago': 'Claims 1 week earlier',
                '52 weeks ago': 'Claims 52 weeks earlier',
                'Week ending': 'Latest week ending',
            })
            section['title'] = 'Unemployment insurance claims'
            section['note'] = (
                'Seasonally adjusted weekly levels. The comparison columns show claim counts, not changes. '
                'The 4-week average is the published average of initial claims. Continued claims generally refer '
                'to an earlier week than initial claims.'
            )
            section['sourceNote'] = 'Source: U.S. Department of Labor, Employment and Training Administration via FRED. Comparisons require the exact reporting week.'

        elif key == 'markets':
            _rename_columns(section, {
                'Close': 'Closing index level',
                '1m (%)': '1-month price return (%)',
                'YTD (%)': 'Year-to-date price return (%)',
                '1y (%)': '12-month price return (%)',
                'Close date': 'Latest close',
            })
            section['title'] = 'Stock market price indexes'
            section['note'] = (
                'Observed daily closing index levels and price returns, not seasonally adjusted. Returns exclude dividends. '
                'Year-to-date starts from the last available close on or before the preceding December 31.'
            )
            section['sourceNote'] = (
                'Sources: S&P Dow Jones Indices and Nasdaq via FRED. Calendar comparisons use a prior available closing '
                'value within seven days of the comparison date. These are closing prices, not intraday quotes.'
            )

        elif key == 'budget':
            _rename_columns(section, {'Deficit': 'Deficit (units shown)', 'Period ending': 'Reporting period'})
            section['title'] = 'Federal budget deficit'
            section['note'] = (
                'Positive values indicate a deficit; negative values indicate a surplus. Dollar amounts are billions of '
                'U.S. dollars, while the fiscal-year deficit-to-GDP ratio is a percent. The federal fiscal year starts in '
                'October. Monthly balances are not seasonally adjusted.'
            )
            section['sourceNote'] = 'Sources: U.S. Treasury and OMB via FRED. Fiscal-year-to-date and trailing-12-month totals require every reported month.'

        elif key == 'context':
            _rename_columns(section, {'Measure': 'Indicator', 'Value': 'Latest value', 'Period': 'Latest month'})
            section['title'] = 'Job openings, quits, underemployment and wages'
            section['note'] = (
                'Job openings are in thousands. The quits rate is quits as a percent of employment. U-6 includes '
                'unemployed and marginally attached people and people working part time for economic reasons, '
                'relative to the labor force plus the marginally attached. Average hourly earnings cover all '
                'employees on private nonfarm payrolls and are nominal dollars per hour.'
            )
            section['sourceNote'] = 'Source: BLS via FRED. Published seasonal adjustment is retained. The latest reporting month can differ across indicators.'

        elif key == 'war':
            _rename_columns(section, {
                'Baseline observation': 'Baseline date',
                'Latest observation': 'Latest observation date',
                'Absolute change': 'Change (units shown)',
                'Change (%)': 'Relative change (%)',
                'Unit / adjustment': 'Level unit / adjustment',
                'Absolute change unit': 'Change unit',
                'Change units': 'Change unit',
                'Baseline unit': 'Value unit',
            })
            section['note'] = (
                'Changes since the user-selected February 28, 2026 start date. Daily and weekly baselines are actual '
                'observations before that date. Monthly baselines use January 2026 because February includes the start '
                'of the war. Baseline and latest dates are shown for every series. These comparisons describe changes '
                'over the period, not the effects caused by the war. Latest observation date identifies when the value '
                'was measured; the page refresh timestamp identifies when the data were retrieved. '
                'WTI and Brent are EIA daily spot-price observations published with a delay, not live futures quotes.'
            )
            section['sourceNote'] = (
                'Sources: FRED and the original data providers linked in each row. Changes use the unit shown: '
                'jobs or claims for counts, index points for indexes, and percentage points for unemployment rates. '
                'Relative change (%) is the proportional change from the baseline value. Daily baselines must fall '
                'within seven days before the start; weekly baselines within fourteen days. Missing values remain unavailable.'
            )
    return sections
