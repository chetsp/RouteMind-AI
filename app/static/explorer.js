const $ = id => document.getElementById(id);
const cell = (tag, text) => { const el = document.createElement(tag); el.textContent = text; return el; };
let offset = 0, total = 0, serial = 0, detailSerial = 0, loading = false;
const limit = 20;
async function get(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Unable to read data (${response.status}). Please try again.`);
  return response.json();
}
function paging() {
  $('previous').disabled = loading || offset === 0;
  $('next').disabled = loading || offset + limit >= total;
}
function closeDetail() { detailSerial++; $('detail').hidden = true; }
async function details(row, vector) {
  const id = ++detailSerial;
  $('detail').hidden = false;
  $('record').textContent = 'Loading…'; $('vector-info').textContent = '';
  $('embedding-panel').hidden = true;
  try {
    const data = vector ? await get(`/api/v1/explorer/vectors/${encodeURIComponent(row.source_id)}`) : row;
    if (id !== detailSerial) return;
    if (vector) {
      const {embedding, ...record} = data;
      $('record').textContent = JSON.stringify(record, null, 2);
      $('vector-info').textContent = `${data.dimension} dimensions · Vector norm ${data.norm.toFixed(6)} · First 16 values: ${embedding.slice(0,16).map(v=>v.toFixed(5)).join(', ')}`;
      $('embedding').textContent = JSON.stringify(embedding, null, 2);
      $('embedding-panel').hidden = false;
    } else $('record').textContent = JSON.stringify(data, null, 2);
    $('detail').scrollIntoView({behavior:'smooth', block:'nearest'});
  } catch (error) { if (id === detailSerial) $('record').textContent = error.message; }
}
async function browse() {
  const id = ++serial, dataset = $('dataset').value;
  closeDetail(); loading = true; paging();
  $('error').hidden = true; $('status').textContent = 'Loading records…';
  $('rows').replaceChildren(); $('columns').replaceChildren(); $('page').textContent = '';
  $('source').textContent = dataset === 'vectors' ? 'Active ChromaDB collection · Stored documents, metadata and embeddings. Search matches literal text; it does not run a semantic query.' : 'SQL reference data · Search matches literal text across all fields. Open a row to see every value.';
  try {
    const params = new URLSearchParams({q:$('search').value, limit, offset});
    const data = await get(`/api/v1/explorer/${dataset === 'vectors' ? 'vectors' : `tables/${dataset}`}?${params}`);
    if (id !== serial) return;
    total = data.total;
    const header = document.createElement('tr');
    for (const col of [...data.columns, 'Details']) header.append(cell('th', col));
    $('columns').append(header);
    for (const row of data.rows) {
      const tr = document.createElement('tr');
      for (const col of data.columns) {
        const td = document.createElement('td');
        const value = row[col];
        td.append(Object.assign(cell('span', value === null || value === undefined ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value)), {className:'cell'})); tr.append(td);
      }
      const td = document.createElement('td'), button = cell('button','View');
      button.type = 'button'; button.setAttribute('aria-label', `View ${row.id || row.source_id || row.carrier_id}`);
      button.addEventListener('click', () => details(row, dataset === 'vectors')); td.append(button); tr.append(td); $('rows').append(tr);
    }
    $('status').textContent = total ? `${total} matching records` : 'No records match your search.';
    $('page').textContent = total ? `${offset+1}–${Math.min(offset+limit,total)} of ${total}` : '0 records';
  } catch (error) {
    if (id !== serial) return;
    total = 0; $('status').textContent = ''; $('error').textContent = error.message; $('error').hidden = false;
  } finally { if (id === serial) { loading = false; paging(); } }
}
$('browse').addEventListener('submit', e => {e.preventDefault(); offset = 0; browse();});
$('dataset').addEventListener('change', () => {offset = 0; browse();});
$('previous').addEventListener('click', () => {offset = Math.max(0,offset-limit); browse();});
$('next').addEventListener('click', () => {offset += limit; browse();});
$('close-detail').addEventListener('click', closeDetail);
get('/api/v1/explorer').then(data => {
  $('summary').textContent = `${Object.entries(data.tables).map(([name,count])=>`${count} ${name}`).join(' · ')} · ${data.vectors} indexed vectors\nActive collection: ${data.collection} · Embedding: ${data.embedding_model} (${data.embedding_backend})${data.warning ? ` · ${data.warning}` : ''}`;
}).catch(error => { $('summary').textContent = error.message; });
browse();
