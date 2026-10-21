const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'PICK'];
const MY_TEAM_KEY = 'ledger.myTeam';
const fmt = n => Math.round(n).toLocaleString('en-US');
const norm = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');
const other = side => (side === 'a' ? 'b' : 'a');
const teamKey = side => (side === 'a' ? 'teamA' : 'teamB');
const ordinal = r => ['1st', '2nd', '3rd'][r - 1] || `${r}th`;
const tierTag = tier => `<span class="tier ${tier.toLowerCase().replace(/ /g, '-')}">${tier}</span>`;

const state = {
  mode: 'league',
  assets: new Map(),        // consensus asset id -> asset (Any player mode)
  freeList: [],
  league: null,             // /api/league
  teams: new Map(),         // roster id -> team
  leagueAssets: new Map(),  // league asset id (Sleeper player id or season-round-r<roster>) -> asset
  free: { a: [], b: [] },
  // lockedBy: 'pick' when chosen in the header (stays when emptied), 'add' when set by the first asset (clears with it)
  lg: { a: [], b: [], teamA: null, teamB: null, lockedBy: { a: null, b: null } },
  seq: 0,
};
const sides = { a: document.querySelector('.side[data-side="a"]'), b: document.querySelector('.side[data-side="b"]') };
const leagueMode = () => state.mode === 'league';
const cur = () => (leagueMode() ? state.lg : state.free);
const lookup = id => (leagueMode() ? state.leagueAssets : state.assets).get(id);
const teamName = rid => state.teams.get(rid)?.team ?? '';

function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { /* private window or blocked storage: the remembered team is a convenience */ }
  return null;
}

function buildLeagueAssets() {
  state.league.teams.forEach(t => {
    state.teams.set(t.roster_id, t);
    t.players.forEach(p => state.leagueAssets.set(p.id, {
      id: p.id, name: p.name, type: 'Player', position: p.position, team: p.team, age: p.age,
      value: p.raw, posRank: state.assets.get(p.id)?.posRank, owner: t.roster_id, taxi: p.taxi,
    }));
    t.picks.forEach(p => state.leagueAssets.set(p.id, {
      id: p.id, name: `${p.season} ${ordinal(p.round)}`, type: 'Pick', position: 'PICK', value: p.value,
      owner: t.roster_id, tier: p.tier, projected: p.projected, from: p.from,
    }));
  });
}

function meta(asset, withOwner = false) {
  let parts;
  if (asset.type === 'Pick') {
    parts = [asset.tier ? asset.tier + (asset.projected ? ' (proj.)' : '') : null, asset.from ? `from ${asset.from}` : null];
  } else {
    parts = [`${asset.position}${asset.posRank ?? ''}`, asset.team, asset.age ? asset.age.toFixed(1) : null,
      asset.taxi ? 'taxi' : null];
  }
  if (withOwner && asset.owner) parts.push(teamName(asset.owner));
  return parts.filter(Boolean).join(', ');
}

function row(asset, { button, onClick, withOwner = false }) {
  const li = document.createElement('li');
  li.className = 'row';
  li.innerHTML = `
    <span class="tag ${asset.position}">${asset.position}</span>
    <span class="name"></span>
    <span class="value num">${fmt(asset.value)}</span>
    <button type="button" class="${button}" aria-label="${button}">${button === 'remove' ? '×' : '+'}</button>`;
  li.querySelector('.name').textContent = asset.name;
  const small = document.createElement('small');
  small.textContent = meta(asset, withOwner);
  li.querySelector('.name').append(small);
  li.querySelector('button').addEventListener('click', onClick);
  return li;
}

/* side header: a team picker in League mode, a plain label in Any player mode */
function renderHead(side) {
  const el = sides[side];
  const select = el.querySelector('.team-pick');
  const team = state.teams.get(state.lg[teamKey(side)]);
  if (leagueMode()) {
    const taken = state.lg[teamKey(other(side))];
    const teams = [...state.teams.values()].sort((x, y) => x.team.localeCompare(y.team));
    select.replaceChildren(new Option('Choose team…', ''), ...teams.map(t => {
      const o = new Option(t.team, t.roster_id);
      o.disabled = t.roster_id === taken;
      return o;
    }));
    select.value = team ? team.roster_id : '';
  }
  el.querySelector('.side-tier').innerHTML = leagueMode() && team ? tierTag(team.tier) : '';
  el.querySelector('.side-rec').textContent = leagueMode() && team ? team.record : '';
  el.querySelector('.search input').placeholder = !leagueMode() ? 'Search players and picks'
    : team ? `Search ${team.team}'s players and picks` : 'Search the league, or choose a team';
}

function renderSide(side, result) {
  const el = sides[side];
  renderHead(side);
  const list = el.querySelector('.rows');
  list.replaceChildren(...cur()[side].map(id =>
    row(lookup(id), { button: 'remove', onClick: () => remove(side, id) })));

  const adj = result && result[side === 'a' ? 'adjA' : 'adjB'];
  if (adj && Math.round(adj) !== 0) {
    const li = document.createElement('li');
    li.className = 'row adjust';
    li.innerHTML = `<span></span><span class="name">Value adjustment</span>
      <span class="value num">${adj > 0 ? '+' : ''}${fmt(adj)}</span><span></span>`;
    list.append(li);
  }

  const picked = cur()[side].map(lookup);
  const counts = {};
  picked.forEach(p => { counts[p.position] = (counts[p.position] || 0) + 1; });
  const breakdown = Object.entries(counts).map(([pos, n]) => `${n} ${pos}`).join(', ');
  el.querySelector('.pieces').textContent = picked.length
    ? `${picked.length} piece${picked.length > 1 ? 's' : ''}: ${breakdown}` : '';

  const total = el.querySelector('.total');
  const final = result ? result[side === 'a' ? 'finalA' : 'finalB'] : picked.reduce((s, p) => s + p.value, 0);
  total.textContent = picked.length ? fmt(final) : '';
  // In Any player mode a side is what a team gets, so the bigger total wins; in League mode it's what a team
  // sends, so the verdict names the winner instead of coloring a total
  total.classList.toggle('win', !leagueMode() && !!result && !result.fair && result.winner.toLowerCase() === side);
  renderBrowse(side);
}

function renderBrowse(side) {
  const details = sides[side].querySelector('.browse');
  const team = leagueMode() && state.teams.get(state.lg[teamKey(side)]);
  details.hidden = !team;
  if (!team) return;
  const taken = new Set([...state.lg.a, ...state.lg.b]);
  const assets = [...state.leagueAssets.values()].filter(a => a.owner === team.roster_id && !taken.has(a.id));
  details.querySelector('summary').innerHTML = `Browse roster <span class="num">${assets.length}</span>`;
  details.querySelector('.browse-body').replaceChildren(...POSITIONS.map(pos => {
    const group = assets.filter(a => a.position === pos).sort((x, y) => y.value - x.value);
    if (!group.length) return '';
    const wrap = document.createElement('div');
    wrap.className = 'browse-group';
    wrap.innerHTML = `<div class="pos-head"><span>${pos}</span><span class="num">${group.length}</span></div>`;
    const ol = document.createElement('ol');
    ol.className = 'rows';
    ol.append(...group.map(a => row(a, { button: 'add', onClick: () => add(side, a.id) })));
    wrap.append(ol);
    return wrap;
  }));
}

function renderResult(result, error) {
  const text = document.querySelector('.verdict-text');
  const fill = document.querySelector('.fill');
  const even = document.querySelector('.even');
  even.hidden = true;
  fill.style.width = '0';

  if (error) {
    text.innerHTML = '<span class="hint"></span>';
    text.firstChild.textContent = error;
    return;
  }
  if (!result) {
    text.innerHTML = `<span class="hint">${leagueMode()
      ? 'Choose a team for each side, or search the league: the first asset added locks a side to its team.'
      : 'Add players or picks to both sides.'}</span>`;
    return;
  }
  const { finalA, finalB } = result;
  const share = Math.abs(finalA - finalB) / (finalA + finalB) / 2;
  fill.style.width = `${share * 100}%`;
  fill.style.left = finalA >= finalB ? `${50 - share * 100}%` : '50%';

  if (result.fair) {
    text.innerHTML = '<span class="fairly">Fair trade.</span> <span class="hint">Within 5% on market value.</span>';
    return;
  }
  const winner = result.winner.toLowerCase();
  const loser = other(winner);
  let addTo;
  if (leagueMode()) {
    // The bigger package is what the winner's partner sends: the team on the other side comes out ahead
    const ahead = teamName(state.lg[teamKey(loser)]);
    text.innerHTML = `<strong></strong> comes out ahead by <span class="delta num">${fmt(result.margin)}</span>
      <span class="hint">on market value.</span>`;
    text.querySelector('strong').textContent = ahead;
    addTo = `${ahead} could add one to even it`;
  } else {
    text.innerHTML = `<strong>Favors Team ${result.winner}.</strong> Add
      <span class="delta num">${fmt(result.margin)}</span> to Team ${loser.toUpperCase()} to even it.`;
    addTo = `Add one of these to Team ${loser.toUpperCase()} to even it`;
  }

  if (result.suggestions.length) {
    even.hidden = false;
    even.classList.toggle('right', loser === 'b');
    even.querySelector('.even-head').textContent = addTo;
    even.querySelector('.even-rows').replaceChildren(...result.suggestions.map(id =>
      row(lookup(id), { button: 'add', onClick: () => add(loser, id) })));
  }
}

function writeHash() {
  const s = cur();
  const p = new URLSearchParams();
  if (!leagueMode()) p.set('mode', 'free');
  if (leagueMode() && s.teamA) p.set('ta', s.teamA);
  if (leagueMode() && s.teamB) p.set('tb', s.teamB);
  if (s.a.length) p.set('a', s.a.join(','));
  if (s.b.length) p.set('b', s.b.join(','));
  const hash = p.toString();
  history.replaceState(null, '', hash ? `#${hash}` : location.pathname);
}

async function update() {
  writeHash();
  const s = cur();
  const seq = ++state.seq;
  let result = null;
  let error = null;
  if (s.a.length && s.b.length) {
    const res = await fetch(leagueMode() ? '/api/league/evaluate' : '/api/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ a: s.a, b: s.b }),
    });
    const body = await res.json();
    if (seq !== state.seq) return;  // a newer edit already went out
    if (res.ok) result = body; else error = body.error;
  }
  renderSide('a', result);
  renderSide('b', result);
  renderResult(result, error);
  const impact = document.querySelector('.impact');
  impact.hidden = !(leagueMode() && result && result.teams);
  if (!impact.hidden) Impact.render(result, state.league.teams.length, { a: state.lg.teamA, b: state.lg.teamB });
}

function setTeam(side, rid, how) {
  const s = state.lg;
  if (s[teamKey(side)] !== rid) s[side] = [];
  s[teamKey(side)] = rid;
  s.lockedBy[side] = rid ? how : null;
  if (side === 'a' && rid && how === 'pick') storage(MY_TEAM_KEY, String(rid));
}

function add(side, id) {
  const s = cur();
  if (s.a.includes(id) || s.b.includes(id)) return;
  if (leagueMode()) {
    const owner = state.leagueAssets.get(id).owner;
    if (owner === s[teamKey(other(side))]) return;
    if (!s[teamKey(side)]) setTeam(side, owner, 'add');
    if (owner !== s[teamKey(side)]) return;
  }
  s[side].push(id);
  update();
}

function remove(side, id) {
  const s = cur();
  s[side] = s[side].filter(x => x !== id);
  if (leagueMode() && !s[side].length && s.lockedBy[side] === 'add') setTeam(side, null, null);
  update();
}

function searchPool(side) {
  const s = cur();
  const taken = new Set([...s.a, ...s.b]);
  if (!leagueMode()) return state.freeList.filter(a => !taken.has(a.id));
  const team = s[teamKey(side)];
  const blocked = s[teamKey(other(side))];
  return [...state.leagueAssets.values()]
    .filter(a => !taken.has(a.id) && (team ? a.owner === team : a.owner !== blocked))
    .sort((x, y) => y.value - x.value);
}

function setupSide(side) {
  const el = sides[side];
  const input = el.querySelector('.search input');
  const list = el.querySelector('.results');
  let matches = [];
  let active = 0;

  const close = () => { list.hidden = true; };
  const choose = asset => { add(side, asset.id); input.value = ''; close(); input.focus(); };

  function render() {
    const q = norm(input.value);
    if (!q) return close();
    const showOwner = leagueMode() && !cur()[teamKey(side)];
    matches = searchPool(side).filter(a => norm(a.name).includes(q)).slice(0, 8);
    active = 0;
    if (!matches.length) {
      list.innerHTML = '<li class="empty">No match</li>';
    } else {
      list.replaceChildren(...matches.map((a, i) => {
        const li = document.createElement('li');
        li.innerHTML = `<span class="tag ${a.position}">${a.position}</span><span class="name"></span>
          <span class="value num">${fmt(a.value)}</span>`;
        li.querySelector('.name').textContent = a.name;
        const small = document.createElement('small');
        small.textContent = meta(a, showOwner);
        li.querySelector('.name').append(small);
        li.classList.toggle('active', i === 0);
        li.addEventListener('mousedown', e => { e.preventDefault(); choose(a); });
        return li;
      }));
    }
    list.hidden = false;
  }

  input.addEventListener('input', render);
  input.addEventListener('blur', close);
  input.addEventListener('keydown', e => {
    if (list.hidden || !matches.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      active = (active + (e.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length;
      [...list.children].forEach((li, i) => li.classList.toggle('active', i === active));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(matches[active]);
    } else if (e.key === 'Escape') {
      close();
    }
  });

  el.querySelector('.team-pick').addEventListener('change', e => {
    setTeam(side, e.target.value ? Number(e.target.value) : null, 'pick');
    update();
  });
}

function setMode(mode) {
  state.mode = mode;
  document.querySelector('.calc').dataset.mode = mode;
  document.querySelectorAll('.mode button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
  update();
}

function restore() {
  const p = new URLSearchParams(location.hash.slice(1));
  const ids = key => (p.get(key) || '').split(',').filter(Boolean);
  if (p.get('mode') === 'free' || !state.league) {
    state.mode = 'free';
    state.free.a = ids('a').filter(id => state.assets.has(id));
    state.free.b = ids('b').filter(id => state.assets.has(id));
    return;
  }
  const team = key => (state.teams.has(Number(p.get(key))) ? Number(p.get(key)) : null);
  const mine = Number(storage(MY_TEAM_KEY));
  const ta = team('ta') ?? (state.teams.has(mine) && Number(p.get('tb')) !== mine ? mine : null);
  const tb = team('tb') !== ta ? team('tb') : null;
  if (ta) setTeam('a', ta, 'pick');
  if (tb) setTeam('b', tb, 'pick');
  ['a', 'b'].forEach(side => ids(side).forEach(id => {
    const asset = state.leagueAssets.get(id);
    if (asset && !state.lg.a.includes(id) && !state.lg.b.includes(id)) {
      if (!state.lg[teamKey(side)]) setTeam(side, asset.owner, 'add');
      if (asset.owner === state.lg[teamKey(side)]) state.lg[side].push(id);
    }
  }));
}

document.querySelector('.clear').addEventListener('click', () => {
  const s = cur();
  s.a = [];
  s.b = [];
  if (leagueMode()) ['a', 'b'].forEach(side => { if (s.lockedBy[side] === 'add') setTeam(side, null, null); });
  update();
});
document.querySelectorAll('.mode button').forEach(b => b.addEventListener('click', () => {
  if (!b.disabled && b.dataset.mode !== state.mode) setMode(b.dataset.mode);
}));

(async () => {
  document.querySelector('.verdict-text').innerHTML = '<span class="hint">Loading league…</span>';
  const data = await (await fetch('/api/assets')).json();
  state.freeList = data.assets;
  data.assets.forEach(a => state.assets.set(a.id, a));
  document.getElementById('built').textContent = data.built;

  try {
    const res = await fetch('/api/league');
    if (!res.ok) throw new Error(res.statusText);
    state.league = await res.json();
    buildLeagueAssets();
    document.querySelector('.league-name').textContent = state.league.league;
    document.querySelector('.calc-note').textContent =
      `${state.teams.size} teams. ${state.league.pick_seasons[0]} picks projected from standings and win-now.`;
  } catch {
    const button = document.querySelector('.mode [data-mode="league"]');
    button.disabled = true;
    button.title = 'League data unavailable';
    document.querySelector('.calc-note').textContent = 'League unavailable, Any player mode only';
  }
  restore();
  setupSide('a');
  setupSide('b');
  setMode(state.mode);
})();
