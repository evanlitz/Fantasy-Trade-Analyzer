const POSITIONS = ['QB', 'RB', 'WR', 'TE'];
const GROUPS = [...POSITIONS, 'PICK'];
const SLOT_LABEL = { SUPER_FLEX: 'SF', WRRB_FLEX: 'W/R', REC_FLEX: 'W/T' };
const MY_TEAM_KEY = 'ledger.myTeam';
// Trade fits: how many rank places an opposite lean (one toward win-now, one toward dynasty) is worth
const DIRECTION_BONUS = 3;
const FITS = 3;

const fmt = n => Math.round(n).toLocaleString('en-US');
const pct = x => `${Math.round(x * 100)}%`;
const ordinal = r => (r % 100 >= 11 && r % 100 <= 13 ? `${r}th` : `${r}${['th', 'st', 'nd', 'rd'][r % 10] || 'th'}`);
const tierTag = tier => `<span class="tier ${tier.toLowerCase().replace(/ /g, '-')}">${tier}</span>`;
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const state = { league: null, ranks: {}, selected: null, sort: 'overall' };
const n = () => state.league.teams.length;
const team = rid => state.league.teams.find(t => t.roster_id === rid);

function myTeam() {
  try { return Number(localStorage.getItem(MY_TEAM_KEY)) || null; } catch { return null; }
}

// rank of every team on a metric, 1 = best; low is better for age
function rankBy(metric, lowIsBetter = false) {
  const sorted = [...state.league.teams].sort((x, y) => (lowIsBetter ? metric(x) - metric(y) : metric(y) - metric(x)));
  return Object.fromEntries(sorted.map((t, i) => [t.roster_id, i + 1]));
}

function computeRanks() {
  state.ranks = {
    overall: rankBy(t => t.overall),
    win_now: Object.fromEntries(state.league.teams.map(t => [t.roster_id, t.win_now_rank])),
    dynasty: Object.fromEntries(state.league.teams.map(t => [t.roster_id, t.dynasty_rank])),
    age: rankBy(t => t.age, true),
  };
  GROUPS.forEach(g => { state.ranks[g] = rankBy(t => t.positions[g]); });
}

/* standings: position ranks as shaded squares, 1st solid ink fading to pale */
function square(rank, hole) {
  const ink = Math.round(10 + ((n() - rank) / Math.max(1, n() - 1)) * 90);
  const style = hole ? '' : ` style="background:color-mix(in srgb, var(--ink) ${ink}%, var(--paper));color:${ink > 55 ? 'var(--paper)' : 'var(--ink)'}"`;
  return `<td class="sq-col"><span class="sq num${hole ? ' hole' : ''}"${style}>${rank}</span></td>`;
}

function renderStandings() {
  const r = state.ranks;
  const key = state.sort;
  const order = [...state.league.teams].sort((x, y) => r[key][x.roster_id] - r[key][y.roster_id]);
  document.querySelector('.power-table tbody').innerHTML = order.map(t => {
    const rid = t.roster_id;
    const sel = rid === state.selected;
    return `<tr data-rid="${rid}" class="${sel ? 'selected' : ''}">
      <td class="r num">${r.overall[rid]}</td><td class="tname">${esc(t.team)}</td><td>${tierTag(t.tier)}</td>
      <td class="r num">${t.record}</td><td class="r num strong">${t.overall.toFixed(1)}</td>
      <td class="r num">${fmt(t.win_now)} <span class="rk">${ordinal(r.win_now[rid])}</span></td>
      <td class="r num">${fmt(t.dynasty)} <span class="rk">${ordinal(r.dynasty[rid])}</span></td>
      ${GROUPS.map(g => square(r[g][rid], sel && r[g][rid] > n() - 3)).join('')}
      <td class="r num">${t.age ? t.age.toFixed(1) : '–'}</td></tr>`;
  }).join('');
  document.querySelectorAll('.power-table th button').forEach(b => b.classList.toggle('active', b.dataset.sort === key));
}

/* depth chart: the best full-strength lineup by Sleeper slot, then bench by start share, then taxi */
function playerCells(p, starter) {
  const meta = [p.team, p.age ? p.age.toFixed(1) : null].filter(Boolean).join(' ') + (p.reserve ? ', IR' : '');
  return `<td><span class="tag ${p.position}">${p.position}</span></td>
    <td class="d-name">${esc(p.name)}<small>${esc(meta)}</small></td>
    <td class="r num${starter ? ' strong' : ''}">${p.taxi ? '–' : pct(p.start)}</td>
    <td class="r num">${fmt(p.value)}</td>`;
}

function renderDepth(t) {
  const byId = Object.fromEntries(t.players.map(p => [p.id, p]));
  const starting = new Set(t.lineup.map(s => s.id).filter(Boolean));
  const bench = t.players.filter(p => !p.taxi && !starting.has(p.id)).sort((a, b) => b.start - a.start || b.value - a.value);
  const taxi = t.players.filter(p => p.taxi);
  const group = (label, count) => `<tr class="d-group"><td colspan="5">${label} <span class="num">${count}</span></td></tr>`;
  const starters = t.lineup.map(s => `<tr class="d-start"><td class="slot">${SLOT_LABEL[s.slot] || s.slot}</td>${s.id
    ? playerCells(byId[s.id], true) : '<td></td><td class="d-empty" colspan="3">Empty</td>'}</tr>`);
  document.querySelector('.depth tbody').innerHTML = starters.join('')
    + (bench.length ? group('Bench', bench.length) + bench.map(p => `<tr><td></td>${playerCells(p, false)}</tr>`).join('') : '')
    + (taxi.length ? group('Taxi', taxi.length) + taxi.map(p => `<tr class="d-taxi"><td></td>${playerCells(p, false)}</tr>`).join('') : '');
  const unvalued = t.unvalued.map(p => `${p.name} (${p.position})`).join(', ');
  document.querySelector('.unvalued').textContent = unvalued ? `No consensus value: ${unvalued}` : '';
}

/* trade fits: strong where this team is weak, weak where it is strong, boosted when tiers point opposite ways */
function fit(me, them) {
  const r = state.ranks;
  const gains = GROUPS.map(g => ({ g, gain: r[g][me.roster_id] - r[g][them.roster_id] }));
  const get = gains.reduce((a, b) => (b.gain > a.gain ? b : a));
  const give = gains.reduce((a, b) => (b.gain < a.gain ? b : a));
  if (get.gain <= 0 || give.gain >= 0) return null;
  // positive: built more for now than for later
  const lean = t => r.dynasty[t.roster_id] - r.win_now[t.roster_id];
  const opposite = lean(me) * lean(them) < 0;
  return { team: them, get: get.g, give: give.g, opposite, buying: lean(me) > 0,
    score: get.gain - give.gain + (opposite ? DIRECTION_BONUS : 0) };
}

function renderFits(t) {
  const r = state.ranks;
  const fits = state.league.teams.filter(o => o.roster_id !== t.roster_id)
    .map(o => fit(t, o)).filter(Boolean).sort((a, b) => b.score - a.score).slice(0, FITS);
  const label = g => (g === 'PICK' ? 'picks' : g);
  document.querySelector('.fits').innerHTML = fits.length ? fits.map(f => {
    const o = f.team.roster_id, me = t.roster_id;
    return `<li><div class="fit-head"><span class="fit-team">${esc(f.team.team)}</span>${tierTag(f.team.tier)}
        <a class="fit-trade" href="/#ta=${me}&tb=${o}">Trade</a></div>
      <p class="fit-why">Their ${label(f.get)} rank ${ordinal(r[f.get][o])} where yours is ${ordinal(r[f.get][me])}.
        Your ${label(f.give)} rank ${ordinal(r[f.give][me])} where theirs is ${ordinal(r[f.give][o])}.${f.opposite
          ? ` ${f.buying ? 'You lean win-now, they lean dynasty.' : 'They lean win-now, you lean dynasty.'}` : ''}</p></li>`;
  }).join('') : '<li class="fit-none">No team complements this roster.</li>';
}

/* picks: seasons down, rounds across */
function renderPicks(t) {
  const rounds = Array.from({ length: state.league.draft_rounds }, (_, i) => i + 1);
  document.querySelector('.pick-board thead').innerHTML =
    `<tr><th></th>${rounds.map(r => `<th>${ordinal(r)}</th>`).join('')}</tr>`;
  document.querySelector('.pick-board tbody').innerHTML = state.league.pick_seasons.map(season => `<tr>
    <th class="num">${season}</th>${rounds.map(round => {
      const held = t.picks.filter(p => p.season === season && p.round === round);
      const away = state.league.teams.find(o => o.roster_id !== t.roster_id
        && o.picks.some(p => p.season === season && p.round === round && p.original === t.roster_id));
      const lines = held.map(p => `<span class="pk" title="${fmt(p.value)}">${p.tier}${p.projected ? '*' : ''}${p.from
        ? ` <small>${esc(p.from)}</small>` : ''}</span>`);
      if (away) lines.push(`<span class="pk gone">to ${esc(away.team)}</span>`);
      return `<td>${lines.join('')}</td>`;
    }).join('')}</tr>`).join('');
  document.querySelector('.picks-note').textContent =
    `Picks marked * are projected for the ${state.league.pick_seasons[0]} draft from standings and win-now; later seasons count as mid.`;
}

function select(rid) {
  const t = team(rid);
  const r = state.ranks;
  state.selected = rid;
  history.replaceState(null, '', `#team=${rid}`);
  document.querySelector('.analysis').hidden = false;
  document.querySelector('.team-name').textContent = t.team;
  document.querySelector('.team-tier').innerHTML = tierTag(t.tier);
  document.querySelector('.team-record').textContent = t.record;
  document.querySelector('.team-rank').textContent = `${ordinal(r.overall[rid])} of ${n()}`;
  document.querySelector('.team-total').textContent = t.overall.toFixed(1);
  const mine = myTeam();
  const link = document.querySelector('.trade-link');
  link.hidden = mine === rid;
  link.href = `/#${mine ? `ta=${mine}&` : ''}tb=${rid}`;
  const stat = (label, value, rank) => `<div class="stat"><span class="stat-label">${label}</span>
    <span class="stat-value num">${value}</span><span class="stat-rank">${ordinal(rank)}</span></div>`;
  document.querySelector('.stats').innerHTML =
    stat('Win-now', fmt(t.win_now), r.win_now[rid])
    + stat('Dynasty', fmt(t.dynasty), r.dynasty[rid])
    + stat(`Picks (${t.picks.length})`, fmt(t.positions.PICK), r.PICK[rid])
    + stat('Age', t.age ? t.age.toFixed(1) : '–', r.age[rid]);
  renderStandings();
  renderDepth(t);
  renderFits(t);
  renderPicks(t);
}

document.querySelector('.power-table thead').addEventListener('click', e => {
  const b = e.target.closest('button[data-sort]');
  if (!b) return;
  state.sort = b.dataset.sort;
  renderStandings();
});
document.querySelector('.power-table tbody').addEventListener('click', e => {
  const tr = e.target.closest('tr[data-rid]');
  if (tr) select(Number(tr.dataset.rid));
});

(async () => {
  state.league = await (await fetch('/api/league')).json();
  computeRanks();
  document.getElementById('league-meta').textContent = `${state.league.league}, ${state.league.season} season. ${n()} teams, `
    + `1QB PPR, picks ${state.league.pick_seasons[0]} to ${state.league.pick_seasons.at(-1)}`;
  const ids = state.league.teams.map(t => t.roster_id);
  const fromHash = Number(new URLSearchParams(location.hash.slice(1)).get('team'));
  select([fromHash, myTeam()].find(id => ids.includes(id)) || ids[0]);
})();
