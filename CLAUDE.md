# Ledger — dynasty trade analyzer

1QB, PPR, no TE premium. Scrapers in `sources/` write `data/<source>.csv`; `combine.py` builds `data/consensus.csv`;
`trade.py` is the evaluator (KTC's value adjustment, ported and verified). `sources/app.py` serves the frontend in `web/`.

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
