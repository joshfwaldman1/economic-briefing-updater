"""Build the public GitHub Pages snapshot from generated economic artifacts.

This command prepares local files only. Review and git push to publish them.
Requires openpyxl for read-only extraction of the supplied workbook.
"""
from pathlib import Path
import argparse
import json
import shutil
import zipfile
from datetime import date
import openpyxl

ROOT=Path(__file__).resolve().parent

def build(workbook,chartbook,charts,retrieved):
    w=openpyxl.load_workbook(workbook,data_only=True,read_only=True)
    config=json.loads((ROOT/'config.json').read_text())
    sections=[]
    def section(key,label,title,kicker,sheet,start,end,cols,heads,note,units,source_col=None):
        rows=[]
        group=config.get({'inflation':'cpi','context':'extra'}.get(key,key),[])
        definitions={item['label']:item['id'] for item in group if item.get('id')}
        for r in range(start,end+1):
            values=[w[sheet].cell(r,c).value for c in cols]
            series_id=definitions.get(values[0])
            if key=='budget':series_id='FYFSGDA188S' if r==7 else 'MTSDS133FMS'
            rows.append({'values':values,'source':f'https://fred.stlouisfed.org/series/{series_id}' if series_id else None})
        sections.append({'key':key,'label':label,'title':title,'kicker':kicker,'columns':heads,'rows':rows,'note':note,'sourceNote':units})
    txt=lambda label:{'label':label,'type':'text'}
    num=lambda label,d=1:{'label':label,'type':'number','digits':d}
    dt=lambda label:{'label':label,'type':'date'}
    section('employment','Employment','Employment by industry','LABOR MARKET','Employment ',3,2+len(config['employment']),[2,3,4,5,10],[txt('Industry'),num('Monthly change',0),num('3-month avg.',0),num('12-month avg.',0),dt('Period')],
            'Monthly payroll changes in people, seasonally adjusted. Subsets overlap their parent industries and should not be added to the total.','Source: BLS establishment survey, retrieved through FRED. Averages require consecutive monthly observations.')
    section('unemployment','Unemployment','Unemployment by race and demographic','LABOR MARKET','Unemployment Rates',4,3+len(config['unemployment']),[2,4,5,6,3],[txt('Population'),num('Rate (%)'),num('1m change (pp)'),num('1y change (pp)'),dt('Period')],
            'Seasonally adjusted. Ages 16 and over unless otherwise noted. Hispanic or Latino ethnicity may be of any race; these groups overlap.','Source: BLS household survey, retrieved through FRED. pp means percentage points.')
    section('inflation','CPI inflation','Consumer price inflation','PRICES','CPI',3,9,[2,3,5,7,11],[txt('Component'),num('MoM (%)'),num('3m annualized (%)'),num('YoY (%)'),dt('Period')],
            'Growth calculated from seasonally adjusted CPI indexes. Annualized changes use index ratios, not rounded monthly changes.','Source: BLS via FRED. SA index-based YoY may differ slightly from the headline NSA convention.')
    section('applications','Business applications','Business applications','BUSINESS ACTIVITY','Business Applications',4,5,[2,4,5,6,3],[txt('Applications'),num('Level',0),num('MoM (%)'),num('YoY (%)'),dt('Period')],
            'Monthly applications, seasonally adjusted. High-propensity applications are a subset of total applications, not additional business formations.','Source: U.S. Census Bureau, retrieved through FRED.')
    section('claims','Jobless claims','Initial and continued claims','LABOR MARKET','Claims',4,6,[2,4,5,6,3],[txt('Measure'),num('Claims',0),num('1 week ago',0),num('52 weeks ago',0),dt('Week ending')],
            'Seasonally adjusted. Continued claims generally refer to an earlier week than initial claims.','Source: U.S. Employment and Training Administration, retrieved through FRED.')
    section('markets','Stock market','Stock market indexes','FINANCIAL MARKETS','Markets',4,6,[2,4,5,6,7,3],[txt('Index'),num('Close'),num('1m (%)'),num('YTD (%)'),num('1y (%)'),dt('Close date')],
            'Daily closing price indexes, not live prices. Changes exclude dividends. Market series are not seasonally adjusted.','Source: S&P Dow Jones Indices and Nasdaq, retrieved through FRED. Calendar lookbacks use the preceding available close within seven days.')
    section('budget','Federal budget','Federal deficit measures','FISCAL POSITION','Federal Budget',4,7,[2,4,5,3],[txt('Measure'),num('Deficit'),txt('Units'),txt('Period ending')],
            'Positive values indicate a deficit; negative values indicate a surplus. Fiscal year to date begins in October. Published budget balances are NSA.','Sources: Treasury, OMB and FRED. Monthly balances are summed for fiscal-year and trailing-year totals.')
    section('participation','Participation','Prime-age participation and employment','LABOR MARKET','Prime-Age Participation',4,5,[2,4,5,6,3],[txt('Measure'),num('Rate (%)'),num('1m change (pp)'),num('1y change (pp)'),dt('Period')],
            'People ages 25–54. Seasonally adjusted. Participation includes both employed people and unemployed people seeking work.','Source: BLS household survey, retrieved through FRED.')
    section('context','Labor context','Job openings, quits and underemployment','LABOR MARKET','Other Indicators',4,6,[2,4,5,3],[txt('Measure'),num('Value'),txt('Units'),dt('Period')],
            'Seasonally adjusted. Job openings and quits come from JOLTS; U-6 includes broader measures of labor underutilization.','Source: BLS, retrieved through FRED. Observation months differ across releases.')
    # Explicit source links for labels shortened in the workbook.
    overrides={'Overall':'PAYEMS','Overall (U-3)':'UNRATE','Consumer sentiment':'UMCSENT','Prime-age employment / population':'LNS12300060','Quits rate':'JTSQUR','U-6 underemployment':'U6RATE'}
    for s in sections:
        for r in s['rows']:
            if r['values'][0] in overrides:r['source']='https://fred.stlouisfed.org/series/'+overrides[r['values'][0]]
    kpis=[
      {'label':'Nonfarm payrolls','value':w['Employment ']['C3'].value,'digits':0,'prefix':'+','suffix':'','detail':'Monthly job change · Aug 2026 · SA'},
      {'label':'Unemployment rate','value':w['Unemployment Rates']['D4'].value,'digits':1,'prefix':'','suffix':'%','detail':'Overall U-3 · Aug 2026 · SA'},
      {'label':'CPI inflation','value':w['CPI']['G3'].value,'digits':1,'prefix':'','suffix':'%','detail':'Year-over-year · Aug 2026 · SA index'},
      {'label':'Fiscal year deficit','value':w['Federal Budget']['D5'].value/1000,'digits':2,'prefix':'$','suffix':'T','detail':'FY to date · Aug 2026 · NSA'},
    ]
    # Labels are derived from each source period when publishing subsequent runs.
    def month(value):return date.fromisoformat(value).strftime('%b %Y')
    kpis[0]['prefix']='+' if kpis[0]['value']>=0 else ''
    kpis[0]['detail']=f"Monthly job change · {month(w['Employment ']['J3'].value)} · SA"
    kpis[1]['detail']=f"Overall U-3 · {month(w['Unemployment Rates']['C4'].value)} · SA"
    kpis[2]['detail']=f"Year-over-year · {month(w['CPI']['K3'].value)} · SA index"
    kpis[3]['detail']=f"FY to date · {month(w['Federal Budget']['C5'].value)} · NSA"
    docs=ROOT/'docs';(docs/'downloads').mkdir(parents=True,exist_ok=True);(docs/'assets').mkdir(exist_ok=True)
    (docs/'data.json').write_text(json.dumps({'retrieved':retrieved,'kpis':kpis,'sections':sections},indent=2)+'\n')
    shutil.copyfile(workbook,docs/'downloads/economic-briefing.xlsx')
    shutil.copyfile(chartbook,docs/'downloads/labor-market-chartbook.docx')
    for name in ['auto_jobs','inflation','g7_real_gdp','selected_state_manufacturing']:
        for ext in ['png','csv']:shutil.copyfile(charts/f'{name}.{ext}',docs/'assets'/f'{name}.{ext}')
    allowed={'.py','.mjs','.json','.command','.md','.txt','.xlsx'}
    with zipfile.ZipFile(docs/'downloads/economic-updater-scripts.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(ROOT.iterdir()):
            if p.is_file() and p.suffix in allowed:archive.write(p,Path('economic-updater')/p.name)
        for name in ['index.html','style.css','app.js','.nojekyll']:
            archive.write(docs/name,Path('economic-updater/docs')/name)
    print(f'Built {len(sections)} indicator groups, four charts and three downloads in docs/.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workbook',type=Path,required=True);p.add_argument('--chartbook',type=Path,required=True);p.add_argument('--charts',type=Path,required=True);p.add_argument('--retrieved',required=True)
    a=p.parse_args();date.fromisoformat(a.retrieved);build(a.workbook,a.chartbook,a.charts,a.retrieved)
