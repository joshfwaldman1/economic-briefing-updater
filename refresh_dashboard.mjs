#!/usr/bin/env node
/** Download FRED observations; all dashboard arithmetic is performed in pandas. */
import { readFile, mkdir, writeFile, rename, unlink } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fetchFredSeries } from './data.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const execute = promisify(execFile);
const CONFIG_GROUPS = ['employment','unemployment','cpi','pce','applications','claims','markets','budget','participation','manufacturing','fuels','wages','extra'];

export function dashboardDefinitions(config, catalog) {
  const definitions = new Map();
  function register(def, group) {
    if (!def.id || (group === 'extra' && def.id === 'UMCSENT')) return;
    const value = {...(definitions.get(def.id) ?? {}), ...def};
    value.group = def.group ?? group;
    value.frequency = (value.frequency ?? 'monthly').toLowerCase();
    value.source = value.source ?? `https://fred.stlouisfed.org/series/${def.id}`;
    if (['employment','manufacturing','manuf_auto'].includes(group)) value.multiplier = value.multiplier ?? 1000;
    definitions.set(def.id,value);
  }
  for (const group of CONFIG_GROUPS) for (const def of config[group] ?? []) register(def,group);
  for (const def of catalog.series ?? []) register(def,def.group);
  return definitions;
}

export async function refreshDashboard({config,catalog,outputDir,cacheDir,fetchSeries=fetchFredSeries,clock=()=>new Date(),python=process.env.PYTHON_BIN || 'python3'}) {
  const definitions=dashboardDefinitions(config,catalog);
  const queue=[...definitions.keys()],raw=new Map(),errors=[];
  const end=clock().toISOString().slice(0,10);
  await Promise.all(Array.from({length:Math.min(4,queue.length)},async()=>{
    while(queue.length){
      const id=queue.shift();
      try {raw.set(id,await fetchSeries(id,{start:'2020-01-01',end,cacheDir}));}
      catch(error){errors.push(`${id}: ${error.message}`);}
    }
  }));
  if(errors.length)throw new Error(`Refresh aborted; published files were not changed. ${errors.length} source(s) failed:\n${errors.join('\n')}`);
  const retrievedAt=clock().toISOString(),snapshotId=randomUUID();
  const exported={retrieved:retrievedAt.slice(0,10),retrievedAt,snapshotId,series:{}};
  for(const [id,def] of definitions)exported.series[id]={...def,...raw.get(id)};
  await mkdir(outputDir,{recursive:true});
  const prefix=join(outputDir,`.refresh-${snapshotId}`);
  const files={series:`${prefix}-series.tmp`,data:`${prefix}-data.tmp`,config:`${prefix}-config.tmp`,catalog:`${prefix}-catalog.tmp`};
  try {
    await writeFile(files.series,JSON.stringify(exported,null,2)+'\n',{flag:'wx'});
    await writeFile(files.config,JSON.stringify(config),{flag:'wx'});
    await writeFile(files.catalog,JSON.stringify(catalog),{flag:'wx'});
    await execute(python,[join(HERE,'calculate_dashboard.py'),'--series',files.series,'--config',files.config,'--catalog',files.catalog,'--output',files.data],{timeout:120000,maxBuffer:1024*1024});
    const dashboard=JSON.parse(await readFile(files.data,'utf8'));
    if(dashboard.snapshotId!==snapshotId || dashboard.retrievedAt!==retrievedAt || !Array.isArray(dashboard.sections))throw new Error('Pandas output failed snapshot validation');
    await rename(files.series,join(outputDir,'series.json'));
    await rename(files.data,join(outputDir,'data.json'));
    return {seriesCount:raw.size,sectionCount:dashboard.sections.length,retrievedAt};
  } finally {
    await Promise.all(Object.values(files).map(path=>unlink(path).catch(error=>{if(error.code!=='ENOENT')throw error;})));
  }
}

export async function main(argv=process.argv.slice(2)) {
  const args={};
  for(let i=0;i<argv.length;i++){
    const key=argv[i];
    if(key==='--help'){
      console.log('Usage: node refresh_dashboard.mjs [--output-dir docs] [--cache-dir cache/dashboard] [--config config.json] [--catalog dashboard_catalog.json]\nDownloads current FRED observations and invokes calculate_dashboard.py. Requires pandas; set PYTHON_BIN to select Python. No extrapolated annual rates are calculated.');
      return;
    }
    if(!['--output-dir','--cache-dir','--config','--catalog'].includes(key)||!argv[i+1]||argv[i+1].startsWith('--'))throw new Error(`Unknown option or missing value: ${key}`);
    args[key.slice(2)]=argv[++i];
  }
  const config=JSON.parse(await readFile(args.config??join(HERE,'config.json'),'utf8'));
  const catalog=JSON.parse(await readFile(args.catalog??join(HERE,'dashboard_catalog.json'),'utf8'));
  const result=await refreshDashboard({config,catalog,outputDir:resolve(args['output-dir']??join(HERE,'docs')),cacheDir:resolve(args['cache-dir']??join(HERE,'cache','dashboard'))});
  console.log(`Refreshed ${result.seriesCount} sources and ${result.sectionCount} tables with pandas at ${result.retrievedAt}.`);
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href)main().catch(error=>{console.error(error.message);process.exitCode=1;});
