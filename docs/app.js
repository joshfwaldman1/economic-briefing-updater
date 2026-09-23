/* Published data snapshot. All user-visible cells are inserted as text. */
const number = (value, digits=1) => typeof value === 'number' ? new Intl.NumberFormat('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(value) : (value ?? 'n.a.');
const date = value => value ? new Intl.DateTimeFormat('en-US',{year:'numeric',month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(value+'T00:00:00Z')) : 'n.a.';
async function start(){
 const response=await fetch('data.json');if(!response.ok)throw Error('Snapshot unavailable');
 const data=await response.json();
 document.querySelector('#retrieved-date').textContent=date(data.retrieved);
 const kpis=document.querySelector('#kpis');
 for(const item of data.kpis){
  const card=document.createElement('div');card.className='kpi';
  const label=document.createElement('p');label.className='kpi-label';label.textContent=item.label;
  const value=document.createElement('strong');value.className='kpi-value';value.textContent=item.prefix+number(item.value,item.digits)+item.suffix;
  const detail=document.createElement('p');detail.className='kpi-detail';detail.textContent=item.detail;
  card.append(label,value,detail);kpis.append(card);
 }
 function show(section){
  for(const button of document.querySelectorAll('#categories button'))button.setAttribute('aria-pressed',String(button.dataset.key===section.key));
  document.querySelector('#section-title').textContent=section.title;
  document.querySelector('#section-kicker').textContent=section.kicker;
  document.querySelector('#section-note').textContent=section.note;
  document.querySelector('#table-count').textContent=`${section.rows.length} ${section.rows.length===1?'series':'series'}`;
  document.querySelector('#section-source').textContent=section.sourceNote;
  const head=document.querySelector('#data-table thead'),body=document.querySelector('#data-table tbody');head.replaceChildren();body.replaceChildren();
  const tr=document.createElement('tr');for(const column of section.columns){const th=document.createElement('th');th.scope='col';th.textContent=column.label;tr.append(th);}head.append(tr);
  for(const row of section.rows){const tr=document.createElement('tr');row.values.forEach((value,i)=>{
   const cell=document.createElement(i===0?'th':'td');if(i===0)cell.scope='row';
   if(i===0&&row.source){const a=document.createElement('a');a.href=row.source;a.textContent=value;cell.append(a);}
   else cell.textContent=section.columns[i].type==='date'?date(value):typeof value==='number'?number(value,section.columns[i].digits??1):value??'n.a.';
   if(value==='n.a.'||value===null)cell.classList.add('cell-muted');if(typeof value==='number'&&value<0)cell.classList.add('negative');tr.append(cell);
  });body.append(tr);}
 }
 const menu=document.querySelector('#categories');
 for(const section of data.sections){const button=document.createElement('button');button.type='button';button.dataset.key=section.key;button.textContent=section.label;button.setAttribute('aria-controls','data-table');button.setAttribute('aria-pressed','false');button.addEventListener('click',()=>show(section));menu.append(button);}
 show(data.sections[0]);
}
start().catch(error=>{document.querySelector('#load-error').hidden=false;console.error(error.message);});
