const state = { assets: [], byId: new Map(), a: [], b: [] };
const sides = { a: document.querySelector('[data-side="a"]'), b: document.querySelector('[data-side="b"]') };
const fmt = n => Math.round(n).toLocaleString('en-US');
const norm = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');
const other = side => (side === 'a' ? 'b' : 'a');

function meta(asset) {
  if (asset.type === 'Pick') return '';
  const parts = [`${asset.position}${asset.posRank}`, asset.team];
  if (asset.age) parts.push(asset.age.toFixed(1));
  return parts.join(' · ');
}

function row(asset, { button, onClick }) {
  const li = document.createElement('li');
  li.className = 'row';
  li.innerHTML = `
    <span class="tag ${asset.position}">${asset.position}</span>
    <span class="name"></span>
    <span class="value num">${fmt(asset.value)}</span>
    <button type="button" class="${button}" aria-label="${button}">${button === 'remove' ? '×' : '+'}</button>`;
  li.querySelector('.name').textContent = asset.name;
  const small = document.createElement('small');
  small.textContent = meta(asset);
  li.querySelector('.name').append(small);
  li.querySelector('button').addEventListener('click', onClick);
  return li;
}

function renderSide(side, result) {
  const el = sides[side];
  const list = el.querySelector('.rows');
  list.replaceChildren(...state[side].map(id =>
    row(state.byId.get(id), { button: 'remove', onClick: () => remove(side, id) })));

  const adj = result && result[side === 'a' ? 'adjA' : 'adjB'];
  if (adj && Math.round(adj) !== 0) {
    const li = document.createElement('li');
    li.className = 'row adjust';
    li.innerHTML = `<span></span><span class="name">Value adjustment</span>
      <span class="value num">${adj > 0 ? '+' : ''}${fmt(adj)}</span><span></span>`;
    list.append(li);
  }

  const picked = state[side].map(id => state.byId.get(id));
  const counts = {};
  picked.forEach(p => { counts[p.position] = (counts[p.position] || 0) + 1; });
  const breakdown = Object.entries(counts).map(([pos, n]) => `${n} ${pos}`).join(', ');
  el.querySelector('.pieces').textContent = picked.length
    ? `${picked.length} piece${picked.length > 1 ? 's' : ''} · ${breakdown}` : '';

  const total = el.querySelector('.total');
  const final = result ? result[side === 'a' ? 'finalA' : 'finalB'] : picked.reduce((s, p) => s + p.value, 0);
  total.textContent = picked.length ? fmt(final) : '';
  total.classList.toggle('win', !!result && !result.fair && result.winner.toLowerCase() === side);
}

function renderResult(result) {
  const text = document.querySelector('.verdict-text');
  const fill = document.querySelector('.fill');
  const even = document.querySelector('.even');
  even.hidden = true;
  fill.style.width = '0';

  if (!result) {
    text.innerHTML = '<span class="hint">Add players or picks to both sides.</span>';
    return;
  }
  const { finalA, finalB } = result;
  const share = Math.abs(finalA - finalB) / (finalA + finalB) / 2;
  fill.style.width = `${share * 100}%`;
  fill.style.left = finalA >= finalB ? `${50 - share * 100}%` : '50%';

  if (result.fair) {
    text.innerHTML = '<span class="fairly">Fair trade</span> <span class="hint">· within 5%</span>';
    return;
  }
  const winner = result.winner.toLowerCase();
  const loser = other(winner);
  text.innerHTML = `<strong>Favors Team ${result.winner}</strong> · add
    <span class="delta num">${fmt(result.margin)}</span> to Team ${loser.toUpperCase()} to even it`;

  if (result.suggestions.length) {
    even.hidden = false;
    even.classList.toggle('right', loser === 'b');
    even.querySelector('.even-head').textContent = `Players to even it — add to Team ${loser.toUpperCase()}`;
    even.querySelector('.even-rows').replaceChildren(...result.suggestions.map(id =>
      row(state.byId.get(id), { button: 'add', onClick: () => add(loser, id) })));
  }
}

async function update() {
  let result = null;
  if (state.a.length && state.b.length) {
    const res = await fetch('/api/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ a: state.a, b: state.b }),
    });
    if (res.ok) result = await res.json();
  }
  renderSide('a', result);
  renderSide('b', result);
  renderResult(result);
}

function add(side, id) {
  if (state.a.includes(id) || state.b.includes(id)) return;
  state[side].push(id);
  update();
}

function remove(side, id) {
  state[side] = state[side].filter(x => x !== id);
  update();
}

function setupSearch(side) {
  const input = sides[side].querySelector('input');
  const list = sides[side].querySelector('.results');
  let matches = [];
  let active = 0;

  const close = () => { list.hidden = true; };
  const choose = asset => { add(side, asset.id); input.value = ''; close(); input.focus(); };

  function render() {
    const q = norm(input.value);
    if (!q) return close();
    const taken = new Set([...state.a, ...state.b]);
    matches = state.assets.filter(a => !taken.has(a.id) && norm(a.name).includes(q)).slice(0, 8);
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
        small.textContent = meta(a);
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
}

document.querySelector('.clear').addEventListener('click', () => {
  state.a = [];
  state.b = [];
  update();
});

(async () => {
  const data = await (await fetch('/api/assets')).json();
  state.assets = data.assets;
  data.assets.forEach(a => state.byId.set(a.id, a));
  document.getElementById('built').textContent = data.built;
  setupSearch('a');
  setupSearch('b');
  update();
})();
