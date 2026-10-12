// Team impact panels for League mode: renders /api/league/evaluate's `teams` (each team's before/after)
const Impact = (() => {
  const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'PICK'];
  const fmt = n => Math.round(n).toLocaleString('en-US');
  const signed = (n, f = fmt) => (Math.round(n) === 0 ? '±0' : `${n > 0 ? '+' : '−'}${f(Math.abs(n))}`);
  const pct = x => `${Math.round(x * 100)}%`;
  const change = (after, before) => (before ? after / before - 1 : 0);
  const signedPct = x => (Math.abs(x) < 0.0005 ? '±0%' : `${x > 0 ? '+' : '−'}${(Math.abs(x) * 100).toFixed(1)}%`);
  const tone = x => (Math.abs(x) < 0.0005 ? '' : x > 0 ? 'pos' : 'neg');
  const tierTag = tier => `<span class="tier ${tier.toLowerCase().replace(/ /g, '-')}">${tier}</span>`;
  const ordinal = r => ['1st', '2nd', '3rd'][r - 1] || `${r}th`;
  const esc = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // One line in plain words, from the two scores the league page already uses (1% either way counts as unchanged)
  function headline(t) {
    const now = change(t.after.win_now, t.before.win_now);
    const dyn = change(t.after.dynasty, t.before.dynasty);
    const word = (x, up, down) => (Math.abs(x) < 0.01 ? null : x > 0 ? up : down);
    const parts = [word(now, 'stronger now', 'weaker now'), word(dyn, 'stronger long-term', 'weaker long-term')].filter(Boolean);
    const text = parts.length ? parts.join(', ') : 'roughly unchanged';
    return text[0].toUpperCase() + text.slice(1);
  }

  // Rank ladder: one cell per team, 1st on the left. Hollow ring = before, filled dot = after, bar = the move.
  function ladder(before, after, n) {
    const lo = Math.min(before, after);
    const hi = Math.max(before, after);
    const dir = after < before ? 'up' : after > before ? 'down' : '';
    let cells = '';
    for (let i = 1; i <= n; i++) {
      const cls = ['cell'];
      if (dir && i >= lo && i <= hi) cls.push('path', dir, i === lo ? 'start' : i === hi ? 'end' : 'mid');
      if (i === before && before !== after) cls.push('was');
      if (i === after) cls.push('now');
      cells += `<span class="${cls.join(' ')}"></span>`;
    }
    return `<div class="ladder" style="--n:${n}">${cells}</div>`;
  }

  function metric(label, key, t, n, note) {
    const b = t.before[key];
    const a = t.after[key];
    const rb = t.before[`${key}_rank`];
    const ra = t.after[`${key}_rank`];
    const x = change(a, b);
    return `<div class="metric" title="${label}: ${fmt(b)} → ${fmt(a)} (${note}) · rank ${rb} → ${ra} of ${n}">
      <span class="metric-label">${label}</span>
      ${ladder(rb, ra, n)}
      <span class="metric-rank num">${rb === ra ? `#${ra}` : `#${rb}→#${ra}`}</span>
      <span class="metric-value num">${fmt(a)}</span>
      <span class="metric-delta num ${tone(x)}">${signedPct(x)}</span>
    </div>`;
  }

  // Diverging bars from a center line, in each position's color; every row is labeled by its tag, so color is
  // never the only cue. `scale` is shared by both teams so their bars compare.
  function positions(t, scale) {
    return POSITIONS.map(pos => {
      const b = t.before.positions[pos];
      const a = t.after.positions[pos];
      const d = a - b;
      const w = scale ? (Math.abs(d) / scale) * 50 : 0;
      const bar = Math.round(d) ? `<span class="div-fill ${pos}" style="left:${d > 0 ? 50 : 50 - w}%;width:${w}%"></span>` : '';
      return `<div class="pos-row" title="${pos}: ${fmt(b)} → ${fmt(a)}">
        <span class="tag ${pos}">${pos}</span>
        <div class="div-bar">${bar}<span class="div-mid"></span></div>
        <span class="num pos-delta ${Math.round(d) ? (d > 0 ? 'pos' : 'neg') : 'zero'}">${signed(d)}</span>
      </div>`;
    }).join('');
  }

  function lineup(t) {
    if (!t.starts.length) return '<p class="impact-empty">No lineup changes</p>';
    return `<ol class="lineup">${t.starts.map(s => {
      const note = s.arrived ? `${pct(s.before)} there → ${pct(s.after)} here` : `${pct(s.before)} → ${pct(s.after)}`;
      return `<li class="lu-row" title="In the best lineup ${note} of simulated weeks">
        <span class="tag ${s.position}">${s.position}</span>
        <span class="lu-name">${esc(s.name)}</span>
        <span class="lu-in">${s.arrived ? 'IN' : ''}</span>
        <span class="lu-meter"><span class="lu-now ${s.position}" style="width:${s.after * 100}%"></span><span class="lu-was" style="width:${s.before * 100}%"></span></span>
        <span class="num lu-pct">${s.arrived ? pct(s.after) : `${pct(s.before)}→${pct(s.after)}`}</span>
      </li>`;
    }).join('')}</ol>`;
  }

  function picks(t) {
    if (!t.pick_tiers.length) return '';
    return `<h4 class="impact-sub">Pick projections</h4><ol class="pick-moves">${t.pick_tiers.map(p =>
      `<li><span class="tag PICK">PICK</span><span>${p.season} ${ordinal(p.round)}${p.from ? ` <small>from ${esc(p.from)}</small>` : ' <small>own</small>'}</span>
        <span class="tier-move"><span class="pick-tier">${p.before}</span>→<span class="pick-tier now">${p.after}</span></span></li>`).join('')}</ol>`;
  }

  function panel(t, n, scale) {
    const moved = t.before.tier !== t.after.tier;
    const dOverall = t.after.overall - t.before.overall;
    return `
      <div class="impact-head">
        <span class="impact-name">${esc(t.team)}</span>
        <span class="impact-rank num">#${t.before.overall_rank}${t.before.overall_rank !== t.after.overall_rank ? `→#${t.after.overall_rank}` : ''} of ${n}</span>
        <span class="impact-overall num" title="Overall ${t.before.overall.toFixed(1)} → ${t.after.overall.toFixed(1)}">${t.after.overall.toFixed(1)}</span>
      </div>
      <div class="impact-body">
        <div class="impact-summary">
          <span class="tier-move">${moved ? `${tierTag(t.before.tier)}<span class="arrow">→</span>${tierTag(t.after.tier)}`
            : `${tierTag(t.after.tier)}<span class="holds">holds</span>`}</span>
          <span class="headline">${headline(t)}</span>
          <span class="num overall-delta ${Math.abs(dOverall) < 0.05 ? '' : dOverall > 0 ? 'pos' : 'neg'}">${signed(dOverall, x => x.toFixed(1))} overall</span>
        </div>
        ${metric('Win-now', 'win_now', t, n, 'simulated weekly lineup')}
        ${metric('Dynasty', 'dynasty', t, n, 'all assets, star-curved')}
        <h4 class="impact-sub">Dynasty value by position</h4>
        <div class="pos-rows">${positions(t, scale)}</div>
        <h4 class="impact-sub">Lineup <small>share of simulated weeks in the best lineup · outline = before</small></h4>
        ${lineup(t)}
        ${picks(t)}
      </div>`;
  }

  function render(result, n) {
    const teams = [result.teams.a, result.teams.b];
    const scale = Math.max(1, ...teams.flatMap(t => POSITIONS.map(p => Math.abs(t.after.positions[p] - t.before.positions[p]))));
    document.querySelector('.impact-team[data-side="a"]').innerHTML = panel(result.teams.a, n, scale);
    document.querySelector('.impact-team[data-side="b"]').innerHTML = panel(result.teams.b, n, scale);
  }

  return { render };
})();
