# Ledger — dynasty trade analyzer

1QB, PPR, no TE premium. `python sources/refresh.py` is the daily run: Sleeper player DB, every scraper, combine, league
check (exit code 1 if any step failed). Scrapers in `sources/` write `data/<source>.csv`; `combine.py` builds `data/consensus.csv`
(refresh also saves a dated copy to `data/history/YYYY-MM-DD.csv`);
`trade.py` is the evaluator (KTC's value adjustment, ported and verified). `league.py` values a Sleeper league's teams
(league ID fixed in `app.py`) and a trade's impact on both teams (`League.trade`; league assets are Sleeper player IDs
and picks as `season-round-r<original roster id>`). Tests: `python -m unittest discover tests` (no network). `sources/app.py` serves the frontend in `web/`: trade calculator (`index.html`) and league
analyzer (`league.html`).

## Frontend design tokens (do not drift from these)

| Token | Value | Use |
|---|---|---|
| `--ink` | `#1C1F1D` | Text, side header bars |
| `--paper` | `#F5F3EE` | Page background |
| `--line` | `#D8D3C8` | Row borders, dividers |
| `--muted` | `#6E6A62` | Meta text, labels |
| `--up` | `#2F6B47` | Winning side, positive delta, primary action |
| `--down` | `#A8432F` | Losing side, negative delta (sparingly) |

- Position tags (text on a pale tint of the same hue): QB `#8C4A32`, RB `#3F6650`, WR `#4A5A6B`, TE `#7E6A2A`, PICK `#6E6A62`
- Team tier tags (same tint style): Juggernaut solid `--up`, Strong Contender `--up`, All In QB rust, Balanced TE ochre,
  Strong Rebuilder WR slate, Purgatory `--down`, Pip Squeak solid `--down`
- Fonts: Archivo (UI, semi-condensed via `font-stretch`), JetBrains Mono (every number)
- Radius: `2px` everywhere. Spacing scale: 4 / 8 / 12 / 16 / 24 px. Rows 32px tall, 4px gap
- No shadows: separation comes from 1px `--line` borders and `--ink` header bars
- Verdict color only on the numbers that matter (winning total, delta, balance bar), never a flooded banner
- Name: "Ledger", wordmark only

## Bans

- No Inter, Roboto, or system-font-only stacks
- No purple/blue/indigo gradients, no gradient text, no glassmorphism
- No big rounded cards with soft drop shadows
- No emoji or icon-in-a-circle feature blocks
- No centered hero section or "Get started" CTA
- No stock shadcn/Tailwind default theme
- No excess whitespace: dense data tool, the tool is the page
- No UI for features the backend doesn't support yet
