import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,writeFile,readdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {refreshDashboard,dashboardDefinitions} from './refresh_dashboard.mjs';

const fixed=new Date('2026-09-23T14:20:00Z');
const catalog={series:[{id:'BEEF',label:'Beef',group:'prices',frequency:'monthly',units:'USD per pound',sa:'NSA',multiplier:1}]};
const sample=id=>({id,sourceUrl:`https://fred.stlouisfed.org/series/${id}`,fetchedAt:fixed.toISOString(),observations:[{date:'2025-08-01',value:5},{date:'2026-07-01',value:6},{date:'2026-08-01',value:6.5}]});

test('transport preserves source definitions and omits unconfigured series',()=>{
 const defs=dashboardDefinitions({unemployment:[{id:'UNRATE',label:'Unemployment',frequency:'Monthly',units:'Percent',sa:'SA'}],pce:[{id:null,label:'Unavailable'}]},catalog);
 assert.equal(defs.get('UNRATE').units,'Percent');
 assert.equal(defs.get('UNRATE').frequency,'monthly');
 assert.equal(defs.size,2);
});

test('failed source retrieval leaves published files unchanged',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'dashboard-source-failure-'));
 try{
  await writeFile(join(dir,'data.json'),'previous data');await writeFile(join(dir,'series.json'),'previous series');
  await assert.rejects(refreshDashboard({config:{},catalog,outputDir:dir,clock:()=>fixed,fetchSeries:async()=>{throw Error('HTTP 500');}}),/published files were not changed/);
  assert.equal(await readFile(join(dir,'data.json'),'utf8'),'previous data');
  assert.equal(await readFile(join(dir,'series.json'),'utf8'),'previous series');
 }finally{await rm(dir,{recursive:true,force:true});}
});

test('failed pandas process leaves both published files unchanged and removes temporary files',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'dashboard-python-failure-'));
 try{
  await writeFile(join(dir,'data.json'),'previous data');await writeFile(join(dir,'series.json'),'previous series');
  await assert.rejects(refreshDashboard({config:{},catalog,outputDir:dir,clock:()=>fixed,fetchSeries:async id=>sample(id),python:join(dir,'python-does-not-exist')}),/ENOENT/);
  assert.equal(await readFile(join(dir,'data.json'),'utf8'),'previous data');
  assert.equal(await readFile(join(dir,'series.json'),'utf8'),'previous series');
  assert.deepEqual((await readdir(dir)).sort(),['data.json','series.json']);
 }finally{await rm(dir,{recursive:true,force:true});}
});

test('online transport hands source observations to pandas and publishes matching snapshots',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'dashboard-pandas-'));
 let calls=0;
 try{
  const result=await refreshDashboard({config:{},catalog,outputDir:dir,clock:()=>fixed,fetchSeries:async(id,options)=>{calls++;assert.equal(options.offline,undefined);return sample(id);}});
  const data=JSON.parse(await readFile(join(dir,'data.json'),'utf8'));
  const raw=JSON.parse(await readFile(join(dir,'series.json'),'utf8'));
  assert.equal(result.seriesCount,1);assert.equal(calls,1);
  assert.equal(data.snapshotId,raw.snapshotId);assert.equal(data.retrievedAt,fixed.toISOString());
  assert.equal(data.sections.find(s=>s.key==='prices').rows[0].values[1],6.5);
  assert.deepEqual((await readdir(dir)).sort(),['data.json','series.json']);
 }finally{await rm(dir,{recursive:true,force:true});}
});
