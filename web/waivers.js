const MY_TEAM_KEY = 'ledger.myTeam';
const POS_COLOR = Object.fromEntries(['QB', 'RB', 'WR', 'TE'].map(p =>
  [p, getComputedStyle(document.documentElement).getPropertyValue(`--${p.toLowerCase()}`).trim()]));
const MAP = { w: 420, h: 380, left: 40, right: 12, top: 12, bottom: 30 };
const MAP_LABELS = 10;
// A change smaller than this share of the biggest change in its column stays uncolored
const STRONG = 0.25;

const fmt = n => Math.round(n).toLocaleString('en-US');
const pct = x => `${Math.round(x * 100)}%`;
const signed = n => (Math.round(n) === 0 ? '0' : `${n > 0 ? '+' : '−'}${fmt(Math.abs(n))}`);
const tierTag = tier => `<span class="tier ${tier.toLowerCase().replace(/ /g, '-')}">${tier}</span>`;
const shortName = name => name.split(' ').slice(1).join(' ') || name;
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const state = { league: null, data: null, pos: '', sort: 'value', hl: null };

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { /* storage blocked */ }
  return null;
}

const visible = () => state.data.free_agents.filter(f => !state.pos || f.position === state.pos);
const belowCut = f => state.data.drop && f.value < state.data.drop.value;

function deltaCell(value, max) {
  const strong = Math.round(value) !== 0 && Math.abs(value) >= STRONG * max;
  const cls = Math.round(value) === 0 ? 'zero' : strong ? (value > 0 ? 'pos' : 'neg') : '';
  return `<td class="r num delta ${cls}">${signed(value)}</td>`;
}

function cutRow(d) {
  return `<tr class="cut-row"><td colspan="8"><div class="cut">
    <span class="cut-label">Cut line</span><span class="tag ${d.position}">${d.position}</span>
    <span class="cut-name">${esc(d.name)}</span><span class="num cut-value">${fmt(d.value)}</span>
    <span class="cut-meta">starts ${pct(d.start)}, dropped for any pickup</span></div></td></tr>`;
}

function renderTable() {
  const list = visible().sort((a, b) => b[state.sort] - a[state.sort]);
  const max = key => Math.max(1, ...list.map(f => Math.abs(f[key])));
  const maxNow = max('win_now_change'), maxDyn = max('dynasty_change');
  const byValue = state.sort === 'value';
  const d = state.data.drop;
  let cutDone = !d || !byValue;

  const rows = [];
  for (const f of list) {
    if (!cutDone && f.value < d.value) {
      rows.push(cutRow(d));
      cutDone = true;
    }
    const meta = [f.team, f.age ? f.age.toFixed(1) : null].filter(Boolean).join(' ');
    const moved = f.tier !== state.data.tier ? tierTag(f.tier) : '';
    rows.push(`<tr data-id="${f.id}" class="${!byValue && belowCut(f) ? 'below' : ''} ${f.id === state.hl ? 'hl' : ''}">
      <td><span class="tag ${f.position}">${f.position}</span></td>
      <td class="fa-name">${esc(f.name)}<small>${esc(meta)}</small></td>
      <td class="r num strong-num">${f.value ? fmt(f.value) : '—'}</td>
      <td class="r num">${fmt(f.now)}</td>
      <td><span class="fa-start"><span class="lu-meter"><span class="lu-now ${f.position}" style="width:${f.start * 100}%"></span></span>
        <span class="num">${pct(f.start)}</span></span></td>
      ${deltaCell(f.win_now_change, maxNow)}${deltaCell(f.dynasty_change, maxDyn)}
      <td class="fa-tier">${moved}</td></tr>`);
  }
  if (!cutDone && list.length) rows.push(cutRow(d));
  document.querySelector('.fa-table tbody').innerHTML = rows.join('')
    || '<tr><td colspan="8" class="fa-empty">No free agents at this position were scored</td></tr>';
  document.querySelectorAll('.fa-table th button').forEach(b => b.classList.toggle('active', b.dataset.sort === state.sort));
  document.querySelector('.wv-count').textContent = `${list.length} free agents, sorted by ${
    document.querySelector(`.fa-table th button[data-sort="${state.sort}"]`).textContent.toLowerCase()}`;
}

function renderMap() {
  const list = visible();
  const svg = document.querySelector('.wv-map svg');
  if (!list.length) { svg.innerHTML = ''; return; }
  const { w, h, left, right, top, bottom } = MAP;
  const domain = values => {
    const lo = Math.min(0, ...values), hi = Math.max(0, ...values);
    const pad = (hi - lo) * 0.08 || 1;
    return [lo - pad, hi + pad];
  };
  const [x0, x1] = domain(list.map(f => f.win_now_change));
  const [y0, y1] = domain(list.map(f => f.dynasty_change));
  const sx = v => left + ((v - x0) / (x1 - x0)) * (w - left - right);
  const sy = v => h - bottom - ((v - y0) / (y1 - y0)) * (h - top - bottom);
  const zx = sx(0), zy = sy(0);

  // Quadrant names sit in each quadrant's outer corner; a quadrant too thin to hold its name goes unnamed
  const corner = (text, x, y, anchor) => {
    const room = anchor === 'end' ? w - right - zx : zx - left;
    return room < text.length * 8 + 12 ? '' : `<text class="quad" x="${x}" y="${y}" text-anchor="${anchor}">${text}</text>`;
  };
  let out = `<rect class="plot" x="${left}" y="${top}" width="${w - left - right}" height="${h - top - bottom}"/>
    <line class="zero" x1="${zx}" x2="${zx}" y1="${top}" y2="${h - bottom}"/>
    <line class="zero" x1="${left}" x2="${w - right}" y1="${zy}" y2="${zy}"/>
    ${corner('Helps both', w - right - 6, top + 14, 'end')}${corner('Stash', left + 6, top + 14, 'start')}
    ${corner('Now only', w - right - 6, h - bottom - 8, 'end')}${corner('Neither', left + 6, h - bottom - 8, 'start')}
    <text class="tick" x="${left}" y="${h - 10}">${signed(x0)}</text>
    <text class="tick" x="${w - right}" y="${h - 10}" text-anchor="end">${signed(x1)}</text>
    <text class="axis" x="${(left + w - right) / 2}" y="${h - 10}" text-anchor="middle">Win-now change</text>
    <text class="tick" x="${left - 4}" y="${top + 8}" text-anchor="end">${signed(y1)}</text>
    <text class="tick" x="${left - 4}" y="${h - bottom}" text-anchor="end">${signed(y0)}</text>
    <text class="axis" transform="translate(12 ${(top + h - bottom) / 2}) rotate(-90)" text-anchor="middle">Dynasty change</text>`;

  // Names beside the biggest overall gains, skipping any that would collide with one already placed
  const boxes = [];
  const labels = [];
  for (const f of [...list].sort((a, b) => b.overall_change - a.overall_change)) {
    if (labels.length >= MAP_LABELS) break;
    const text = shortName(f.name), width = text.length * 5.6 + 2;
    const cx = sx(f.win_now_change), cy = sy(f.dynasty_change);
    const flip = cx + 7 + width > w - right;
    const box = { x: flip ? cx - 7 - width : cx + 7, y: cy - 6, w: width, h: 12 };
    if (boxes.some(b => box.x < b.x + b.w && b.x < box.x + box.w && box.y < b.y + b.h && b.y < box.y + box.h)) continue;
    boxes.push(box);
    labels.push(`<text class="label" x="${flip ? cx - 7 : cx + 7}" y="${cy + 3.5}" text-anchor="${flip ? 'end' : 'start'}">${esc(text)}</text>`);
  }
  out += list.map(f => `<circle data-id="${f.id}" cx="${sx(f.win_now_change)}" cy="${sy(f.dynasty_change)}" r="4"
    fill="${POS_COLOR[f.position]}" class="${f.id === state.hl ? 'hl' : ''}"><title>${esc(f.name)}</title></circle>`).join('');
  svg.innerHTML = out + labels.join('');
}

function highlight(id) {
  if (id === state.hl) return;
  state.hl = id;
  document.querySelectorAll('.fa-table tr[data-id]').forEach(tr => tr.classList.toggle('hl', tr.dataset.id === id));
  document.querySelectorAll('.wv-map circle').forEach(c => c.classList.toggle('hl', c.dataset.id === id));
  const dot = id && document.querySelector(`.wv-map circle[data-id="${id}"]`);
  if (dot) dot.parentNode.append(dot);
}

function render() {
  const d = state.data;
  document.querySelector('.wv-tier').innerHTML = tierTag(d.tier);
  document.querySelector('.wv-rec').textContent = d.record;
  document.querySelector('.wv-spots').innerHTML = d.full
    ? `<span class="num">${d.spots}/${d.limit}</span> full`
    : `<span class="num">${d.spots}/${d.limit}</span>, ${d.limit - d.spots} open`;
  document.querySelector('.wv-cut').innerHTML = d.drop
    ? `drops <strong>${esc(d.drop.name)}</strong> <span class="num">${fmt(d.drop.value)}</span>` : 'no drop needed';
  document.getElementById('wv-meta').textContent =
    `${state.league.league}, ${d.free_agents.length} free agents scored for ${d.team}`;
  renderTable();
  renderMap();
}

async function load(rosterId) {
  store(MY_TEAM_KEY, rosterId);
  history.replaceState(null, '', `#team=${rosterId}`);
  document.querySelector('.waivers').classList.add('loading');
  state.data = await (await fetch(`/api/league/free-agents?team=${rosterId}`)).json();
  document.querySelector('.waivers').classList.remove('loading');
  state.hl = null;
  render();
}

document.querySelector('.wv-pos').addEventListener('click', e => {
  const b = e.target.closest('button');
  if (!b) return;
  state.pos = b.dataset.pos;
  document.querySelectorAll('.wv-pos button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  renderTable();
  renderMap();
});

document.querySelector('.fa-table thead').addEventListener('click', e => {
  const b = e.target.closest('button[data-sort]');
  if (!b) return;
  state.sort = b.dataset.sort;
  renderTable();
});

document.querySelector('.fa-table tbody').addEventListener('mouseover', e => {
  const tr = e.target.closest('tr[data-id]');
  if (tr) highlight(tr.dataset.id);
});
document.querySelector('.wv-map svg').addEventListener('mouseover', e => {
  const c = e.target.closest('circle[data-id]');
  if (c) highlight(c.dataset.id);
});
document.querySelector('.fa-table tbody').addEventListener('mouseleave', () => highlight(null));
document.querySelector('.wv-map svg').addEventListener('mouseleave', () => highlight(null));

(async () => {
  state.league = await (await fetch('/api/league')).json();
  const teams = [...state.league.teams].sort((a, b) => a.team.localeCompare(b.team));
  const select = document.querySelector('.team-pick');
  select.innerHTML = teams.map(t => `<option value="${t.roster_id}">${esc(t.team)}</option>`).join('');
  const ids = teams.map(t => t.roster_id);
  const fromHash = Number(new URLSearchParams(location.hash.slice(1)).get('team'));
  const saved = Number(store(MY_TEAM_KEY));
  const rid = [fromHash, saved].find(id => ids.includes(id)) || ids[0];
  select.value = rid;
  select.addEventListener('change', () => load(Number(select.value)));
  load(rid);
})();
