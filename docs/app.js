/* Public source data. User-visible values are inserted as text, never HTML. */
const number = (value, digits = 1) => typeof value === 'number' && Number.isFinite(value)
  ? new Intl.NumberFormat('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits}).format(value)
  : (value ?? 'n.a.');

function parsedDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:T|$)/.test(value)) return null;
  const parsed = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function date(value, frequency) {
  const parsed = parsedDate(value);
  if (!parsed) return 'n.a.';
  if (frequency === 'quarterly') return `Q${Math.floor(parsed.getUTCMonth() / 3) + 1} ${parsed.getUTCFullYear()}`;
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric', month: 'short', ...(frequency === 'monthly' ? {} : {day: 'numeric'}), timeZone: 'UTC'
  }).format(parsed);
}

function timestamp(value) {
  const parsed = parsedDate(value);
  if (!parsed) return null;
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    hour12: false, timeZone: 'UTC', timeZoneName: 'short'
  }).format(parsed);
}

function sourceURL(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const url = new URL(value, window.location.href);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch { return null; }
}

function sourceLink(label, url) {
  const link = document.createElement('a');
  link.href = sourceURL(url);
  link.textContent = label;
  return link;
}

function downloadDates(data) {
  const entries = Array.isArray(data.downloads) ? data.downloads : Object.entries(data.downloads ?? {}).map(([key, item]) => ({key, ...item}));
  const list = document.querySelector('.download-list');
  const setup = list.querySelector('a:not([download])');
  for (const item of entries) {
    const path = item.path ?? item.href ?? '';
    const href = sourceURL(path);
    if (!href) continue;
    const key = item.key ?? (path.endsWith('.xlsx') ? 'workbook' : path.endsWith('.docx') ? 'chartbook' : null);
    let link = ['workbook', 'chartbook'].includes(key) ? document.querySelector(`[data-download="${key}"]`) : null;
    if (!link) {
      link = document.createElement('a'); link.download = '';
      const content = document.createElement('span');
      const label = document.createElement('strong'); label.textContent = item.label ?? 'Download data';
      const description = document.createElement('small'); description.className = 'download-description';
      const refreshed = document.createElement('small'); refreshed.className = 'download-date';
      content.append(label, description, refreshed);
      const arrow = document.createElement('span'); arrow.setAttribute('aria-hidden', 'true'); arrow.textContent = '↓';
      link.append(content, arrow);
      list.insertBefore(link, setup);
    }
    link.href = href;
    if (item.label) link.querySelector('strong').textContent = item.label;
    if (item.description) link.querySelector('small').textContent = item.description;
    const value = item.updatedAt ?? item.retrievedAt ?? item.retrieved ?? item.date;
    const detail = link.querySelector('.download-date');
    if (detail && parsedDate(value)) detail.textContent = `File refreshed ${value.includes('T') ? timestamp(value) : date(value)}`;
  }
  if (data.downloadsNote) document.querySelector('#downloads-note').textContent = data.downloadsNote;
}

async function start() {
  const response = await fetch('data.json', {cache: 'no-cache'});
  if (!response.ok) throw Error('Data unavailable');
  const data = await response.json();
  if (!Array.isArray(data.sections) || !data.sections.length) throw Error('No indicator tables found');
  document.querySelector('#retrieved-date').textContent = timestamp(data.retrievedAt) ?? (parsedDate(data.retrieved) ? date(data.retrieved) : 'Unavailable');
  downloadDates(data);

  const kpis = document.querySelector('#kpis');
  for (const item of data.kpis ?? []) {
    const href = sourceURL(item.source);
    const card = document.createElement(href ? 'a' : 'div');
    card.className = 'kpi';
    if (href) {
      card.href = href;
      card.setAttribute('aria-label', `${item.label}: ${item.prefix ?? ''}${number(item.value, item.digits ?? 1)}${item.suffix ?? ''}. Open source chart on FRED.`);
    }
    const label = document.createElement('p'); label.className = 'kpi-label'; label.textContent = item.label;
    const value = document.createElement('strong'); value.className = 'kpi-value'; value.textContent = `${item.prefix ?? ''}${number(item.value, item.digits ?? 1)}${item.suffix ?? ''}`;
    const detail = document.createElement('p'); detail.className = 'kpi-detail'; detail.textContent = item.detail;
    card.append(label, value, detail);
    if (href) { const hint = document.createElement('span'); hint.className = 'kpi-link'; hint.textContent = 'View source chart ↗'; card.append(hint); }
    kpis.append(card);
  }

  const scroll = document.querySelector('.table-scroll');
  function updateScrollHint() {
    document.querySelector('#scroll-hint').hidden = scroll.scrollWidth <= scroll.clientWidth + 1;
  }
  function show(section) {
    for (const button of document.querySelectorAll('#categories button')) button.setAttribute('aria-pressed', String(button.dataset.key === section.key));
    document.querySelector('#section-title').textContent = section.title;
    document.querySelector('#section-kicker').textContent = section.kicker ?? 'ECONOMIC DATA';
    document.querySelector('#section-note').textContent = section.note ?? '';
    document.querySelector('#table-count').textContent = `${section.rows.length} series`;
    document.querySelector('#section-source').textContent = section.sourceNote ?? '';
    document.querySelector('#data-table caption').textContent = `${section.title}. ${section.note ?? ''}`;
    const head = document.querySelector('#data-table thead'), body = document.querySelector('#data-table tbody');
    head.replaceChildren(); body.replaceChildren();
    const heading = document.createElement('tr');
    for (const column of section.columns) {
      const th = document.createElement('th'); th.scope = 'col'; th.textContent = column.label;
      if (column.description) th.title = column.description;
      heading.append(th);
    }
    head.append(heading);
    for (const row of section.rows) {
      const tr = document.createElement('tr');
      row.values.forEach((value, index) => {
        const column = section.columns[index] ?? {};
        const cell = document.createElement(index === 0 ? 'th' : 'td');
        if (index === 0) {
          cell.scope = 'row';
          if (sourceURL(row.source)) cell.append(sourceLink(value, row.source));
          else cell.textContent = value ?? 'n.a.';
          if (Array.isArray(row.sources) && row.sources.length) {
            const sources = document.createElement('span'); sources.className = 'row-sources';
            sources.append(document.createTextNode('Sources: '));
            row.sources.filter(item => sourceURL(item.url)).forEach((item, i) => {
              if (i) sources.append(document.createTextNode(' · '));
              sources.append(sourceLink(item.label, item.url));
            });
            cell.append(sources);
          }
        } else {
          cell.textContent = column.type === 'date' ? date(value, column.frequency ?? row.frequency ?? section.frequency)
            : typeof value === 'number' ? number(value, row.digits?.[index] ?? column.digits ?? 1) : value ?? 'n.a.';
        }
        if (value === 'n.a.' || value === null || value === undefined) cell.classList.add('cell-muted');
        if (typeof value === 'number' && value < 0) cell.classList.add('negative');
        tr.append(cell);
      });
      body.append(tr);
    }
    scroll.scrollLeft = 0;
    updateScrollHint();
  }
  const menu = document.querySelector('#categories');
  for (const section of data.sections) {
    const button = document.createElement('button'); button.type = 'button'; button.dataset.key = section.key; button.textContent = section.label;
    button.setAttribute('aria-controls', 'data-table'); button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => {
      show(section);
      history.replaceState(null, '', `#indicator=${encodeURIComponent(section.key)}`);
    }); menu.append(button);
  }
  function linkedSection() {
    const key = new URLSearchParams(window.location.hash.slice(1)).get('indicator');
    return data.sections.find(section => section.key === key);
  }
  show(linkedSection() ?? data.sections[0]);
  window.addEventListener('hashchange', () => { const section = linkedSection(); if (section) show(section); });
  window.addEventListener('resize', updateScrollHint);
}
start().catch(error => {
  document.querySelector('#load-error').hidden = false;
  document.querySelector('#retrieved-date').textContent = 'Unavailable';
  document.querySelector('#section-title').textContent = 'Data unavailable';
  console.error(error.message);
});
