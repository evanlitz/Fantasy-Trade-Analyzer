const POSITIONS = ['QB', 'RB', 'WR', 'TE'];
const fmt = n => Math.round(n).toLocaleString('en-US');
const pct = x => `${Math.round(x * 100)}%`;
const tierTag = tier => `<span class="tier ${tier.toLowerCase().replace(/ /g, '-')}">${tier}</span>`;
let league = null;
let ranks = {};

// rank of every team on a metric, 1 = best; low is better for age
function rankBy(metric, lowIsBetter = false) {
  const sorted = [...league.teams].sort((x, y) => (lowIsBetter ? metric(x) - metric(y) : metric(y) - metric(x)));
  return Object.fromEntries(sorted.map((t, i) => [t.roster_id, i + 1]));
}

function computeRanks() {
  ranks = {
    overall: rankBy(t => t.overall),
    age: rankBy(t => t.age, true),
  };
  [...POSITIONS, 'PICK'].forEach(pos => { ranks[pos] = rankBy(t => t.positions[pos]); });
}

const n = () => league.teams.length;
const avg = metric => league.teams.reduce((s, t) => s + metric(t), 0) / n();

function standing(rank) {
  const third = Math.round(n() / 3);
  return rank <= third ? 'Strength' : rank > n() - third ? 'Weakness' : '';
}

function stat(label, value, rank, hint) {
  return `<div class="stat"><span class="stat-label">${label}</span>
    <span class="stat-value num">${value}</span>
    <span class="stat-rank">#${rank} of ${n()}${hint ? ` · ${hint}` : ''}</span></div>`;
}

function renderStrength(t) {
  const rows = [...POSITIONS, 'PICK'].map(pos => ({ label: pos, tag: pos, metric: x => x.positions[pos], rank: ranks[pos] }));
  document.querySelector('.strength tbody').innerHTML = rows.map(r => {
    const value = r.metric(t);
    const max = Math.max(...league.teams.map(r.metric));
    const mean = avg(r.metric);
    const delta = value - mean;
    const rank = r.rank[t.roster_id];
    return `<tr>
      <td><span class="tag ${r.tag}">${r.label}</span></td>
      <td class="r num">${fmt(value)}</td>
      <td class="r num">${rank}</td>
      <td class="bar-col"><div class="meter" title="${r.label}: ${fmt(value)} · league avg ${fmt(mean)} · max ${fmt(max)}">
        <div class="meter-fill" style="width:${(value / max) * 100}%"></div>
        <div class="meter-avg" style="left:${(mean / max) * 100}%"></div></div></td>
      <td class="r num ${delta >= 0 ? 'pos' : 'neg'}">${delta >= 0 ? '+' : '−'}${fmt(Math.abs(delta))}</td>
      <td class="standing">${standing(rank)}</td></tr>`;
  }).join('');
}

function playerRow(p) {
  const li = document.createElement('li');
  li.className = 'row' + (p.taxi ? ' taxi' : '');
  const meta = [p.team, p.age ? p.age.toFixed(1) : null, p.taxi ? null : `starts ${pct(p.start)}`].filter(Boolean).join(' · ');
  li.innerHTML = `<span class="tag ${p.position}">${p.position}</span><span class="name"></span>
    <span class="value num">${fmt(p.value)}</span><span class="flag">${p.taxi ? 'TAXI' : ''}</span>`;
  li.querySelector('.name').textContent = p.name;
  const small = document.createElement('small');
  small.textContent = meta;
  li.querySelector('.name').append(small);
  li.title = p.taxi ? `Taxi: ${fmt(p.raw)} × 0.9 · can't start` : `In the best lineup ${pct(p.start)} of simulated weeks · 2026 value ${fmt(p.now)}`;
  return li;
}

function renderRoster(t) {
  const roster = document.querySelector('.roster');
  roster.replaceChildren(...POSITIONS.map(pos => {
    const group = document.createElement('div');
    group.className = 'pos-group';
    const players = t.players.filter(p => p.position === pos);
    group.innerHTML = `<div class="pos-head"><span>${pos} · ${players.length}</span></div>`;
    const list = document.createElement('ol');
    list.className = 'rows';
    list.append(...players.map(playerRow));
    group.append(list);
    return group;
  }));
}

function renderPicks(t) {
  document.querySelector('.picks-note').textContent =
    `${league.pick_seasons[0]} projected from standings + win-now · later seasons mid`;
  document.querySelector('.pick-rows').replaceChildren(...t.picks.map(p => {
    const li = document.createElement('li');
    li.className = 'row';
    const round = ['1st', '2nd', '3rd'][p.round - 1] || `${p.round}th`;
    li.innerHTML = `<span class="tag PICK">PICK</span><span class="name"></span>
      <span class="value num">${fmt(p.value)}</span><span class="flag"></span>`;
    li.querySelector('.name').textContent = `${p.season} ${round}`;
    const small = document.createElement('small');
    small.textContent = [p.tier + (p.projected ? ' (proj.)' : ''), p.from ? `from ${p.from}` : null].filter(Boolean).join(' · ');
    li.querySelector('.name').append(small);
    return li;
  }));
  const unvalued = t.unvalued.map(p => `${p.name} (${p.position})`).join(', ');
  document.querySelector('.unvalued').textContent = unvalued ? `No consensus value: ${unvalued}` : '';
}

function renderPower(selected) {
  const cell = (v, extra = '') => `<td class="r num ${extra}">${v}</td>`;
  document.querySelector('.power-table tbody').replaceChildren(...league.teams.map((t, i) => {
    const tr = document.createElement('tr');
    tr.className = t.roster_id === selected ? 'selected' : '';
    tr.innerHTML = cell(i + 1) + '<td class="tname"></td>' + `<td>${tierTag(t.tier)}</td>` + cell(t.record)
      + cell(t.overall.toFixed(1), 'strong')
      + cell(`${fmt(t.win_now)} <span class="rk">#${t.win_now_rank}</span>`)
      + cell(`${fmt(t.dynasty)} <span class="rk">#${t.dynasty_rank}</span>`)
      + POSITIONS.map(pos => cell(ranks[pos][t.roster_id], ranks[pos][t.roster_id] === 1 ? 'best' : '')).join('')
      + cell(t.age ? t.age.toFixed(1) : '–');
    tr.querySelector('.tname').textContent = t.team;
    tr.addEventListener('click', () => select(t.roster_id));
    return tr;
  }));
}

function select(rosterId) {
  const t = league.teams.find(x => x.roster_id === rosterId);
  history.replaceState(null, '', `#team=${rosterId}`);
  document.querySelector('.analysis').hidden = false;
  document.querySelector('.team-name').textContent = t.team;
  document.querySelector('.team-tier').innerHTML = tierTag(t.tier);
  document.querySelector('.team-record').textContent = t.record;
  document.querySelector('.team-rank').textContent = `#${ranks.overall[rosterId]} of ${n()}`;
  document.querySelector('.team-total').textContent = t.overall.toFixed(1);
  document.querySelector('.stats').innerHTML =
    stat('Win-now', fmt(t.win_now), t.win_now_rank, 'expected weekly lineup, 2026 values')
    + stat('Dynasty', fmt(t.dynasty), t.dynasty_rank, 'all assets, star-curved')
    + stat('Picks', fmt(t.positions.PICK), ranks.PICK[rosterId], `${t.picks.length} picks`)
    + stat('Age', t.age ? t.age.toFixed(1) : '–', ranks.age[rosterId], 'value-weighted, #1 youngest');
  renderStrength(t);
  renderRoster(t);
  renderPicks(t);
  renderPower(rosterId);
}

(async () => {
  league = await (await fetch('/api/league')).json();
  computeRanks();
  document.getElementById('league-meta').textContent =
    `${league.league} · ${league.season} · ${n()} teams · 1QB PPR · picks ${league.pick_seasons.join('–')}`;
  const fromHash = Number(new URLSearchParams(location.hash.slice(1)).get('team'));
  select(league.teams.some(t => t.roster_id === fromHash) ? fromHash : league.teams[0].roster_id);
})();
