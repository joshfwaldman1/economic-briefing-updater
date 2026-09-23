#!/usr/bin/env node
/** Economic briefing updater. Run with --help. All data are snapshots at retrieval time. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fetchFredSeries,latestDate,valueAt,monthShift,growth,averageJobChange,meanJobChangeBetween,decemberGrowth,yearlyMean} from './data.mjs';

const HERE=path.dirname(fileURLToPath(import.meta.url));
const HELP=`Usage: node update_workbook.mjs [options]
  --input FILE       Workbook to update (default: template.xlsx beside script)
  --output FILE      New workbook; existing files are never overwritten
  --config FILE      Series mappings (default: config.json beside script)
  --as-of YYYY-MM-DD Latest observation allowed; NOT a historical data vintage
  --offline          Explicitly use downloaded cache, labeled in workbook
  --strict           Abort without workbook output if any data download fails
  --render-dir DIR   Save sheet previews for review
  --help             Show this message
Outputs include a JSON refresh report beside the workbook. No API key is needed.
Prices, rates and levels use published seasonality; no custom seasonal adjustment.
`;

export function parseArgs(argv){
 const result={};
 for(let i=0;i<argv.length;i++){
  const key=argv[i];
  if(['--offline','--strict','--help'].includes(key))result[key.slice(2)]=true;
  else if(['--input','--output','--config','--as-of','--render-dir'].includes(key)){
   if(!argv[i+1]||argv[i+1].startsWith('--'))throw Error(`Missing value for ${key}`);
   result[key.slice(2)]=argv[++i];
  } else throw Error(`Unknown option: ${key}`);
 }
 return result;
}
async function artifact(){
 const roots=[HERE,process.env.ARTIFACT_TOOL_ROOT,path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node')].filter(Boolean);
 for(const root of roots){try {const req=createRequire(path.join(root,'package.json'));return await import(pathToFileURL(req.resolve('@oai/artifact-tool')).href);}catch(e){if(e.code!=='MODULE_NOT_FOUND'&&e.code!=='ERR_MODULE_NOT_FOUND')throw e;}}
 throw Error('Cannot locate @oai/artifact-tool. Run using the Codex workspace runtime, or set ARTIFACT_TOOL_ROOT to its Node dependency directory.');
}
const iso=()=>new Date().toISOString();
const days=(a,b)=>(new Date(a)-new Date(b))/86400000;
const addDays=(date,n)=>new Date(new Date(date).getTime()+n*86400000).toISOString().slice(0,10);
const safe=n=>Number.isFinite(n)?n:'n.a.';
const delta=(s,d,n)=>{const a=valueAt(s,d),b=valueAt(s,monthShift(d,-n));return a==null||b==null?null:a-b;};
const nearest=(s,d,tolerance=7)=>{const o=s?.observations.filter(x=>x.date<=d).at(-1);return o&&days(d,o.date)<=tolerance?o:null;};
const monthlySum=(s,start,end)=>{let total=0;for(let d=start;d<=end;d=monthShift(d,1)){const n=valueAt(s,d);if(n==null)return null;total+=n;}return total;};
const mul=(n,m)=>n==null?null:n*m;

export async function main(argv=process.argv.slice(2)){
 const args=parseArgs(argv);if(args.help){console.log(HELP);return;}
 const config=JSON.parse(await fs.readFile(args.config??path.join(HERE,'config.json'),'utf8'));
 const asOf=args['as-of']??iso().slice(0,10);
 if(!/^\d{4}-\d{2}-\d{2}$/.test(asOf)||Number.isNaN(Date.parse(asOf))||new Date(asOf).toISOString().slice(0,10)!==asOf)throw Error('Invalid --as-of date');
 const input=path.resolve(args.input??path.join(HERE,'template.xlsx'));
 const output=path.resolve(args.output??path.join(HERE,'runs',`Gene Master Prep ${iso().replaceAll(':','-').replace('.','-')}.xlsx`));
 if(!output.toLowerCase().endsWith('.xlsx'))throw Error('--output must end in .xlsx');
 await fs.access(input);
 const reportPath=output.replace(/\.xlsx$/i,'')+'.refresh.json';
 if(input===output)throw Error('Input and output must differ');
 for(const p of [output,reportPath]){try{await fs.access(p);throw Error(`Output already exists: ${p}`);}catch(e){if(e.code!=='ENOENT')throw e;}}
 if(!/^\d{4}-\d{2}-01$/.test(config.termBaseline)||Number.isNaN(Date.parse(config.termBaseline))||new Date(config.termBaseline).toISOString().slice(0,10)!==config.termBaseline)throw Error('termBaseline must be a valid first-of-month YYYY-MM-01');
 const groups=['cpi','pce','employment','unemployment','participation','goods','manufacturing','applications','claims','markets','extra'];
 const definitions=groups.flatMap(g=>config[g]??[]).filter(x=>x.id);
 definitions.push(...config.fuels,...config.wages,...config.budget);
 const unique=new Map(definitions.map(x=>[x.id,x]));
 for(const [id,def] of unique){if(!/^[A-Z0-9]+$/.test(id)||!def.label)throw Error(`Invalid series mapping ${id}`);}
 for(const group of groups){const ids=(config[group]??[]).map(x=>x.id).filter(Boolean);if(new Set(ids).size!==ids.length)throw Error(`Duplicate series in ${group}`);}
 const cacheDir=path.join(HERE,'cache');const data=new Map(),failures=[];
 const start=`${Math.min(2022,Number(config.termBaseline.slice(0,4))-1,Number(asOf.slice(0,4))-3)}-01-01`;
 const queue=[...unique.keys()];
 await Promise.all(Array.from({length:4},async()=>{while(queue.length){const id=queue.shift();try{data.set(id,await fetchFredSeries(id,{start,end:asOf,cacheDir,offline:!!args.offline}));}catch(e){failures.push({id,message:e.message});console.error(`${id}: ${e.message}`);}}}));
 if(!data.size)throw Error('No data available. Workbook was not written.');
 if(args.strict&&failures.length)throw Error(`${failures.length} series failed; --strict prevented workbook output.`);
 console.log(`Loaded ${data.size}/${unique.size} series. Updating workbook…`);
 const {FileBlob,SpreadsheetFile}=await artifact();
 const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(input));
 const log=[],changed=[];
 const sheet=name=>{try{return wb.worksheets.getItem(name);}catch{return wb.worksheets.add(name);}};
 const write=(s,range,values)=>s.getRange(range).values=values;
 const cell=(s,address,v)=>write(s,address,[[v]]);
 function status(def,d){if(!d)return 'Unavailable';const age=days(asOf,d);const stale=age>(def.maxAgeDays??(def.frequency==='Daily'?10:def.frequency==='Weekly'?21:def.frequency==='Annual'?730:100));return `${args.offline?'Cached; ':''}${stale?'Lagged; check source':'Retrieved'}`;}
 function entry(name,def,notes=''){
  const s=data.get(def.id),d=s?latestDate(s):null;const state=status(def,d);
  log.push({sheet:name,metric:def.label,series:def.id,observation:d,status:state,seasonality:def.sa??'SA',units:def.units??'',notes:notes||failures.find(x=>x.id===def.id)?.message||'',source:`https://fred.stlouisfed.org/series/${def.id}`,fetchedAt:s?.fetchedAt??null});
  return {s,d,state};
 }
 function manual(name,label,note){log.push({sheet:name,metric:label,series:'',observation:null,status:'Manual; not refreshed',seasonality:'',units:'',notes:note,source:'',fetchedAt:null});}
 function banner(s,title){cell(s,'A1',title);s.getRange('A1').format.font={name:'Arial',size:12,bold:true};s.getRange('A1').format.fill='#FFF2CC';}
 function newTable(name,headers,rows,note){
  const s=sheet(name);s.getRange('A1:L150').clear({applyTo:'contents'});
  banner(s,`${name} — retrieved ${asOf}${args.offline?' (cached)':''}`);
  write(s,'B3',[headers]);if(rows.length)write(s,'B4',rows.map(r=>r.map(safeText)));
  const last=String.fromCharCode(65+headers.length);
  s.getRange(`B3:${last}${rows.length+3}`).format.font={name:'Arial',size:11};
  s.getRange(`B3:${last}3`).format={fill:'#CEE1F1',font:{name:'Arial',size:11,bold:true},wrapText:true,rowHeight:32};
  s.getRange(`B4:${last}${Math.max(4,rows.length+3)}`).format.rowHeight=30;
  s.getRange(`B3:${last}${Math.max(4,rows.length+3)}`).format.verticalAlignment='center';
  s.getRange('A1:A150').format.columnWidth=3;
  s.getRange('B1:B150').format.columnWidth=43;
  s.getRange(`C1:${last}150`).format.columnWidth=18;
  s.getRange(`C4:${last}${Math.max(4,rows.length+3)}`).setNumberFormat('#,##0.0;[Red](#,##0.0);0.0');
  s.getRange(`B4:B${Math.max(4,rows.length+3)}`).format.wrapText=true;
  s.showGridLines=false;
  if(note){cell(s,`B${rows.length+6}`,note);}
  changed.push({name,range:`A1:${last}${rows.length+7}`});return s;
 }
 function safeText(v){return typeof v==='number'?safe(v):v??'n.a.';}
 // Existing inflation blocks retain their format and row order.
 for(const [name,key] of [['CPI','cpi'],['PCE','pce']]){
  const s=sheet(name);banner(s,`${name} refreshed ${asOf}`);
  write(s,'H2:I2',[['2023 Dec/Dec','2024 Dec/Dec']]);
  write(s,'K2:L2',[['Period','Refresh status']]);s.getRange('K2:L9').format.columnWidth=25;
  for(const def of config[key]){
   if(!def.id){cell(s,`L${def.row}`,'Manual; not refreshed');manual(name,def.label,def.note);continue;}
   const {s:series,d,state}=entry(name,def,'Growth from SA levels; percentages in points. Historical columns are Dec/Dec.');
   const vals=d?[growth(series,d,1),growth(series,d,1,true),growth(series,d,3,true),growth(series,d,6,true),growth(series,d,12),decemberGrowth(series,2023),decemberGrowth(series,2024)]:Array(7).fill(null);
   write(s,`C${def.row}:I${def.row}`,[vals.map(safe)]);cell(s,`K${def.row}`,d??'n.a.');cell(s,`L${def.row}`,state);
  }
  s.getRange('C3:I9').setNumberFormat('0.0;[Red](0.0);0.0');
  s.getRange('H2:I2').format.wrapText=true;s.getRange('H2:I2').format.rowHeight=32;
  cell(s,'K11','SA index growth; percent points.');changed.push({name,range:'A1:L14'});
 }
 // Employment records replace the managed table; original source links move below it.
 {
  const s=sheet('Employment ');let footer=s.getRange('B6:C9').values;
  if(footer[0]?.[0]!=='Latest report:')footer=[['Latest report:','https://www.bls.gov/news.release/pdf/empsit.pdf'],['EconVitals:','https://econvitals.org/labor/#sec-employment'],['FRED - All:','https://fred.stlouisfed.org/series/PAYEMS'],['FRED - Manufacturing:','https://fred.stlouisfed.org/series/MANEMP']];
  const baseStyle=s.getRange('B3:H3');
  for(let r=4;r<config.employment.length+3;r++)s.getRange(`B${r}:H${r}`).copyFrom(baseStyle,'all');
  s.getRange('B3:K100').clear({applyTo:'all'});
  banner(s,`Payrolls refreshed ${asOf}`);
  write(s,'B2:H2',[['Industry','Monthly change','3-month avg.','12-month avg.',`Avg. since ${config.termBaseline.slice(0,7)}`,'2024 avg.','2023 avg.']]);
  write(s,'J2:K2',[['Period','Status']]);
  const rows=config.employment.map(def=>{
   const {s:series,d,state}=entry('Employment ',def,def.kind==='subset'?`Subset of ${def.overlaps_with}; do not add to parent.`:'Monthly change in persons; published levels in thousands.');
   return [def.label,...(d?[averageJobChange(series,d,1),averageJobChange(series,d,3),averageJobChange(series,d,12),meanJobChangeBetween(series,config.termBaseline,d),averageJobChange(series,'2024-12-01',12),averageJobChange(series,'2023-12-01',12)]:Array(6).fill(null)).map(safe),null,d??'n.a.',state];
  });write(s,'B3',rows);
  const n=rows.length+3;write(s,`B${n+2}`,footer);
  cell(s,`B${n+7}`,'Jobs are persons, seasonally adjusted. Subsets overlap their parent industry.');
  cell(s,`B${n+8}`,`Term average: monthly changes after the ${config.termBaseline.slice(0,7)} baseline. No gaps are interpolated.`);
  s.getRange(`B2:B${n}`).format.columnWidth=41;s.getRange(`B3:B${n}`).format.wrapText=true;
  s.getRange(`B3:K${n}`).format.rowHeight=31;s.getRange('C2:H2').format.wrapText=true;s.getRange('C2:H2').format.rowHeight=42;
  s.getRange(`B3:H${n-1}`).format.font={name:'Times New Roman',size:12,color:'#000000'};
  s.getRange(`B3:K${n-1}`).format.verticalAlignment='center';
  s.getRange(`B3:H${n-1}`).format.borders={preset:'all',style:'thin',color:'#B5B5B5'};
  s.getRange(`C3:H${n}`).setNumberFormat('#,##0;[Red](#,##0);0');s.getRange(`C2:H${n}`).format.columnWidth=20;
  s.getRange(`J2:K${n}`).format.columnWidth=23;s.freezePanes.freezeRows(2);
  changed.push({name:'Employment ',range:`A1:K${n}`});
 }
 function rates(name,defs,note){
  const rows=defs.map(def=>{const {s,d,state}=entry(name,def,note);return [def.label,d,d?valueAt(s,d):null,d?delta(s,d,1):null,d?delta(s,d,12):null,state];});
  return newTable(name,['Measure','Period','Rate (%)','1m change (pp)','1y change (pp)','Status'],rows,note);
 }
 rates('Unemployment Rates',config.unemployment,'SA, ages 16+ unless labeled otherwise. Hispanic ethnicity may be of any race. Groups overlap.');
 rates('Prime-Age Participation',config.participation,'SA rates. Changes are percentage points.');
 {
  const a=data.get('CES0500000003'),c=data.get('CPIAUCSL');
  const real=a&&c?{observations:a.observations.filter(o=>valueAt(c,o.date)>0).map(o=>({date:o.date,value:100*o.value/valueAt(c,o.date)}))}:null;
  const s=sheet('Wage Growth');banner(s,`Wages refreshed ${asOf}`);write(s,'C2:H2',[['MoM (%)','MoM a.r. (%)','3m a.r. (%)','YoY (%)','2024 Dec/Dec','2023 Dec/Dec']]);
  cell(s,'J2','Period');
  for(const [r,label,series] of [[3,'Average Hourly Earnings',a],[4,'Real AHE (calculated)',real]]){
   const d=series?latestDate(series):null;cell(s,`B${r}`,label);
   write(s,`C${r}:H${r}`,[(d?[growth(series,d,1),growth(series,d,1,true),growth(series,d,3,true),growth(series,d,12),decemberGrowth(series,2024),decemberGrowth(series,2023)]:Array(6).fill(null)).map(safe)]);
   cell(s,`J${r}`,d??'n.a.');
  }entry('Wage Growth',config.wages[0],'Real AHE = nominal AHE / SA CPI-U × 100. Exact matching months.');
  cell(s,'B7','SA; percentages in points. Real earnings calculated with CPI-U.');s.getRange('C3:H4').setNumberFormat('0.0');s.getRange('B2:B4').format.columnWidth=33;s.getRange('C2:H2').format.wrapText=true;s.getRange('C2:H2').format.rowHeight=35;changed.push({name:'Wage Growth',range:'A1:J8'});
 }
 {
  const def={id:'UMCSENT',label:'Consumer sentiment',sa:'NSA',frequency:'Monthly',units:'Index 1966 Q1=100'};const {s,d,state}=entry('Michigan Consumer Sentiment',def,'FRED publication is delayed by one month at source request.');
  newTable('Michigan Consumer Sentiment',['Measure','Period','Index','Prior month','Year ago','Status'],[[def.label,d,d?valueAt(s,d):null,d?valueAt(s,monthShift(d,-1)):null,d?valueAt(s,monthShift(d,-12)):null,state]],'University of Michigan, Surveys of Consumers © UMCSENT, retrieved from FRED. FRED data delayed one month.');
 }
 for(const [name,defs] of [['Prices of specific goods',config.goods],['Business Applications',config.applications]]){
  const rows=defs.map(def=>{const {s,d,state}=entry(name,def);return [def.label,d,d?valueAt(s,d):null,d?growth(s,d,1):null,d?growth(s,d,12):null,state];});
  const st=newTable(name,['Measure','Period','Level','MoM (%)','YoY (%)','Status'],rows,name==='Business Applications'?'Monthly applications, SA. High propensity is a subset of total applications; applications are not business formations.':'CPI price indexes, SA. Index levels use their source base periods; growth in percent.');
  if(name==='Business Applications')st.getRange(`D4:D${rows.length+3}`).setNumberFormat('#,##0');
 }
 {
  const rows=config.manufacturing.map(def=>{const {s,d,state}=entry('Manuf',def);return [def.label,d,d?mul(valueAt(s,d),1000):null,d?averageJobChange(s,d,1):null,d?mul(delta(s,d,12),1000):null,state];});
  const s=sheet('Manuf');write(s,'B8',[['Industry or state','Period','Jobs','1m change','1y change','Status'],...rows.map(r=>r.map(safeText))]);
  s.getRange('B8:G8').format={fill:'#CEE1F1',font:{name:'Arial',size:11,bold:true}};s.getRange('B8:B18').format.columnWidth=43;s.getRange('C8:G18').format.columnWidth=19;s.getRange('B9:G18').format.rowHeight=30;s.getRange('B9:B18').format.wrapText=true;s.getRange('D9:F18').setNumberFormat('#,##0');cell(s,'B19','Selected states and auto industries; SA persons. States can have different reporting months.');changed.push({name:'Manuf',range:'A1:G20'});
 }
 {
  const s=sheet('Gasoline & Diesel');cell(s,'A1','AAA manual; EIA refreshed below');cell(s,'G8',`EIA retrieved ${asOf}`);write(s,'C11:F11',[['Latest week','1 week ago','4 weeks ago','52 weeks ago']]);
  for(const [i,def] of config.fuels.entries()){
   const {s:series,d,state}=entry('Gasoline & Diesel',def,'EIA weekly prices, USD/gallon, NSA. Comparisons require exact observation dates.');
   const vals=d?[0,7,28,364].map(n=>nearest(series,addDays(d,-n),0)?.value??null):Array(4).fill(null);write(s,`C${12+i}:F${12+i}`,[vals.map(safe)]);cell(s,`H${12+i}`,d??'n.a.');cell(s,`I${12+i}`,state);
   const weekMean=year=>{const x=series?.observations.filter(o=>o.date.startsWith(`${year}-`))??[];return x.length>=52&&Number(x[0].date.slice(5,7))===1&&Number(x.at(-1).date.slice(5,7))===12?x.reduce((a,b)=>a+b.value,0)/x.length:null;};
   const hist=d?[nearest(series,'2026-02-23',0)?.value,nearest(series,'2025-01-20',0)?.value,weekMean(2024),weekMean(2023)]:Array(4).fill(null);write(s,`C${16+i}:F${16+i}`,[hist.map(safe)]);
  }write(s,'E15:F15',[['2024 weekly mean','2023 weekly mean']]);s.getRange('E15:F15').format.wrapText=true;s.getRange('E15:F15').format.rowHeight=34;s.getRange('C12:F17').setNumberFormat('0.00');s.getRange('C11:F11').format.wrapText=true;s.getRange('C11:F11').format.rowHeight=32;manual('Gasoline & Diesel','AAA','Daily AAA figures remain as supplied; not automatically refreshed.');changed.push({name:'Gasoline & Diesel',range:'A1:J21'});
 }
 {
  const rows=config.claims.map(def=>{const {s,d,state}=entry('Claims',def);return [def.label,d,d?valueAt(s,d):null,d?nearest(s,addDays(d,-7),0)?.value:null,d?nearest(s,addDays(d,-364),0)?.value:null,state];});
  const s=newTable('Claims',['Measure','Week ending','Claims','1 week ago','52 weeks ago','Status'],rows,'Seasonally adjusted. Continued claims generally refer to an earlier week than initial claims.');s.getRange('D4:F6').setNumberFormat('#,##0');
 }
 {
  const rows=config.markets.map(def=>{const {s,d,state}=entry('Markets',def,'Closing price index; price returns exclude dividends. Not seasonally adjusted.');const pct=target=>{const b=nearest(s,target,7)?.value;return b&&d?100*(valueAt(s,d)/b-1):null;};return [def.label,d,d?valueAt(s,d):null,d?pct(monthShift(d,-1)):null,d?pct(`${Number(d.slice(0,4))-1}-12-31`):null,d?pct(monthShift(d,-12)):null,state];});
  newTable('Markets',['Index','Close date','Level','1m price (%)','YTD price (%)','1y price (%)','Status'],rows,'FRED daily closing indexes, NSA. Returns exclude dividends. Calendar lookbacks use the preceding available close within seven days.');
 }
 {
  const def=config.budget.find(x=>x.id==='MTSDS133FMS');const {s,d,state}=entry('Federal Budget',def,'Treasury cash balance, NSA. Source surplus is positive; displayed deficit reverses sign. Fiscal year begins October.');
  const fy=d?`${Number(d.slice(0,4))-(Number(d.slice(5,7))<10?1:0)}-10-01`:null;
  const rows=[['Monthly deficit',d,d?mul(valueAt(s,d),-0.001):null,'USD billions',state],['Fiscal year to date deficit',d,d?mul(monthlySum(s,fy,d),-0.001):null,'USD billions',state],['Trailing 12 months deficit',d,d?mul(monthlySum(s,monthShift(d,-11),d),-0.001):null,'USD billions',state]];
  const annual=config.budget.find(x=>x.id==='FYFSGDA188S');if(annual){const x=entry('Federal Budget',annual,'Fiscal-year deficit/GDP: source balance sign reversed.');rows.push(['Fiscal year deficit / GDP',x.d?`FY ${x.d.slice(0,4)}`:null,x.d?mul(valueAt(x.s,x.d),-1):null,'% of GDP',x.state]);}
  newTable('Federal Budget',['Measure','Period ending','Deficit','Units','Status'],rows,'NSA Treasury measures. Positive deficit means spending exceeds receipts; negative means surplus. No seasonal adjustment applied.');
 }
 {
  const rows=config.extra.filter(d=>d.id!=='UMCSENT').map(def=>{const {s,d,state}=entry('Other Indicators',def);return [def.label,d,d?valueAt(s,d):null,def.units,state];});
  newTable('Other Indicators',['Measure','Period','Value','Units','Status'],rows,'Additional labor context. Levels and rates retain published units and seasonal adjustment.');
 }
 manual('Calendar','Release schedule','Calendar table preserved. Release dates require manual review; consult the linked calendar.');cell(sheet('Calendar'),'G2','Manual schedule; not refreshed');
 manual('G7 comparisons','Custom GDP graph','Download the supplied custom FRED chart with download_fred_charts.py. Graph transformations are preserved there.');cell(sheet('G7 comparisons'),'A1','Custom GDP chart: use the graph download script');
 cell(sheet('G7 comparisons'),'A3','User supplied G7 GDP graph');cell(sheet('G7 comparisons'),'A4','https://fred.stlouisfed.org/graph/?g=1tBaE');
 cell(sheet('G7 comparisons'),'A6','National real GDP levels have different units. Use growth rates for cross-country comparisons.');
 changed.push({name:'G7 comparisons',range:'A1:J10'});
 changed.push({name:'Calendar',range:'A1:J21'});
 const rows=log.map(x=>[x.sheet,x.metric,x.series,x.observation,x.status,x.seasonality,x.units,x.notes,x.source]);
 const ls=newTable('Refresh Log',['Sheet','Metric','Series','Last observation','Status','Adjustment','Source units','Notes','Source'],rows,'SA = seasonally adjusted. NSA = not seasonally adjusted. n.a. means a required observation is missing. Workbook is a snapshot.');
 ls.getRange('B3:J3').format.rowHeight=35;ls.getRange(`B4:J${rows.length+3}`).format.rowHeight=44;ls.getRange(`B4:J${rows.length+3}`).format.wrapText=true;ls.getRange('C1:C150').format.columnWidth=42;ls.getRange('I1:I150').format.columnWidth=65;ls.getRange('J1:J150').format.columnWidth=60;ls.getRange('D1:H150').format.columnWidth=23;ls.freezePanes.freezeRows(3);
 wb.recalculate();
 console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:20},summary:'formula error check'})).ndjson);
 if(args['render-dir']){
  await fs.mkdir(args['render-dir'],{recursive:true});
  for(const c of changed){try {let index=0;while(wb.worksheets.getItemAt(index).name!==c.name)index++;const range=c.name==='Refresh Log'?'A1:J12':c.range;const p=await wb.render({sheetIndex:index,range,scale:1,format:'png'});await fs.writeFile(path.join(args['render-dir'],`${c.name.trim()}.png`),new Uint8Array(await p.arrayBuffer()));}catch(e){console.error(`Preview ${c.name}: ${e.message}`);}}
 }
 const report={retrievedAt:iso(),asOf,offline:!!args.offline,input,output,seriesLoaded:data.size,seriesRequested:unique.size,failures,rows:log,methodology:{termBaseline:config.termBaseline,percentages:'Percentage points, not Excel fractions',vintage:'Current revised observations, not historical vintages'}};
 await fs.mkdir(path.dirname(output),{recursive:true});
 const temp=`${output}.tmp-${process.pid}`;
 try {
  await (await SpreadsheetFile.exportXlsx(wb)).save(temp);
  const bundledPython=path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3');
  let python=process.env.GENE_PYTHON;
  if(!python){try{await fs.access(bundledPython);python=bundledPython;}catch{python='python3';}}
  await promisify(execFile)(python,[path.join(HERE,'fix_workbook_links.py'),temp,'--footer-row',String(config.employment.length+5)]);
  await fs.link(temp,output);
 }finally{await fs.rm(temp,{force:true});await fs.rm(`${temp}.inspect.ndjson`,{force:true});}
 await fs.writeFile(reportPath,JSON.stringify(report,null,2),{flag:'wx'});
 console.log(`Wrote ${output}\n${failures.length} download failures; ${log.filter(x=>x.status.startsWith('Manual')).length} manual sections. See Refresh Log.`);
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(e=>{console.error(`Update failed: ${e.message}`);process.exitCode=1;});
