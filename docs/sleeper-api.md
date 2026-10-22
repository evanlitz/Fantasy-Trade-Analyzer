# Sleeper API reference

Everything the Sleeper API can do, with what we tested ourselves marked **(verified)**: we called it live against
league `1395495049021652992` (Big kirko) on 2026-10-22, in week 7 of the 2026 season. Anything we did not call
ourselves is marked **(reported)**, with where the report came from.

Sleeper documents only part of this API, at [docs.sleeper.com](https://docs.sleeper.com/). The rest is what Sleeper's
own app uses. It is unsupported and can change or disappear without notice, so anything we build on it needs a check
that fails loudly when it changes (the way `points.check_scoring` does).

---

## 1. Rate limit: read this first

> **Stay under 1000 calls a minute, or Sleeper may block your IP.** That is the only limit Sleeper publishes
> ([docs.sleeper.com](https://docs.sleeper.com/)). A block hits every Sleeper call from this machine and network,
> including the Sleeper app on the same Wi-Fi. Sleeper doesn't say how long a block lasts.

**In this project:**

- **Every Sleeper call goes through `common.sleeper_get`.** Never call Sleeper with `requests` directly (CLAUDE.md
  rule).
  - It spaces calls at least 0.5s apart across all threads (`SLEEPER_INTERVAL`), which caps one process at 120 calls
    a minute. That's 12% of the limit, so the app server and a refresh running at the same time stay far below it.
  - On HTTP 429 it waits for `Retry-After` if Sleeper sends it, otherwise 2s, 4s, 8s, and retries 3 times
    (`SLEEPER_RETRIES`). Then it raises.
- **Sleeper doesn't tell you how close you are to the limit (verified).** No response we saw had `X-RateLimit-*` or
  similar headers, so 429 is the only warning. Treat any 429 as "already too close" and back off, never retry fast.
- **Keep loops bounded.** The danger is a loop over players, weeks or leagues. For example, pulling each player's
  stats one call at a time is about 700 calls; at full speed that is close to the limit within a minute. Use the bulk
  endpoint instead: one call per week returns every player.
- **`/players/nfl` is about 5MB.** Sleeper asks that it be called at most once a day and saved. We save it to
  `data/sleeper_players.json` (`ids.sleeper_players(force=True)` runs once per refresh).
- **Sleeper's CDN caches responses (verified).** Every response carries Cloudflare's `cache-control: public,
  s-maxage=N`, so calling more often than N seconds returns the same cached data and gains nothing:

| Endpoint | CDN cache (`s-maxage`) |
|---|---|
| `/state/nfl` | 60s |
| `/league/{id}/matchups/{week}` | 60s |
| `/draft/{id}` | 30s |
| `/user/{id}`, `/league/{id}/drafts`, `/user/{id}/drafts/...` | 120s |
| League, users, rosters, transactions, traded picks, brackets | 300s |
| Stats for one week, per-player stats and projections | 300 to 600s (60s on per-player weekly stats) |
| Projections, schedule, depth charts, research, trending, single player | 600s |
| Past seasons' stats | 3600s |
| `/draft/{id}/picks` (completed draft) | 86,400s (1 day) |
| `/draft/{id}/traded_picks` (completed draft) | 259,200s (3 days) |
| Player news | 60s |

**Budget today:** a full `refresh.py` makes about 25 Sleeper calls (state, league and 12 weekly projection pulls in
`points.pull`, about 4 more in each check, and 5 to load the league). The app server makes 5 when its 10-minute
league cache (`LEAGUE_CACHE_SECONDS`) expires. Both are under 1% of the limit.

**Other terms:**

- The API is free for **non-commercial** use only; commercial use needs a license from Sleeper.
- Sleeper asks for attribution when trending-player data is shown.

---

## 2. Hosts and conventions

| Host | Use |
|---|---|
| `https://api.sleeper.app/v1` | The documented API |
| `https://api.sleeper.app` or `https://api.sleeper.com` (no `/v1`) | The undocumented endpoints. Both hosts returned identical data for every path we tried (verified) |
| `https://sleepercdn.com` | Images: avatars, player headshots |
| `https://sleeper.com/graphql` | Sleeper's private, logged-in API. Out of scope (section 6) |

- **GET only.** There is no write access without logging in (section 6).
- **No authentication**, no API key.
- **IDs are strings:** user, league, draft, player and transaction IDs (for example `"9221"`). Defenses use the team
  code as the player ID (`"DET"`).
  - **`roster_id` is an integer** (1 to the number of teams) in rosters, matchups, traded picks and brackets.
  - In `/draft/{id}/picks`, `roster_id` comes back as a **string** (see the `sleeper-api` memory).
- **Errors (documented):** 400 bad request, 404 not found, 429 too many requests, 500 server error, 503 maintenance.
  - Unknown paths under `/v1` return a 404 HTML redirect page, not JSON (verified).
- **`sport`** is `nfl` everywhere here. Sleeper also serves `nba`, and `/state/nba` works (verified).

---

## 3. Documented endpoints (`https://api.sleeper.app/v1`)

All 19 are listed at [docs.sleeper.com](https://docs.sleeper.com/), and each was **verified** live.

### NFL state

**`GET /state/nfl`** returns where the season is.

```json
{"week": 7, "leg": 7, "season": "2026", "season_type": "regular", "league_season": "2026",
 "previous_season": "2025", "season_start_date": "2026-09-09", "display_week": 7,
 "league_create_season": "2026", "season_has_scores": true}
```

- `season_type` is `pre`, `regular` or `post`.
- `week` is the current week: a week stays current until it is over.
- Everything that depends on the week reads it from here (`points.pull`, `points.check`, `points.check_scoring`).

### Users

**`GET /user/{username}`** and **`GET /user/{user_id}`** return the same object.

- Useful fields: `user_id`, `username`, `display_name`, `avatar`.
- The other fields (`email`, `phone`, `real_name`, `token` and more) are always `null` in public responses
  (verified).

**`GET /user/{user_id}/leagues/nfl/{season}`** lists every league that user is in that season, as full league objects.

**`GET /user/{user_id}/drafts/nfl/{season}`** lists every draft that user is in that season.

### Leagues

**`GET /league/{league_id}`** returns the league.

- **Identity and season:** `name`, `status` (`pre_draft`, `drafting`, `in_season`, `complete`), `season`,
  `total_rosters`, `draft_id`, `previous_league_id` (follow it to walk back through past seasons).
- **`roster_positions`:** the starting slots and bench in order, for example `QB, RB, RB, WR, WR, TE, FLEX, FLEX, K,
  DEF, BN x10`.
- **`scoring_settings`:** 148 keys in this league. These keys are the same as the stat keys in stats and projections,
  so league points are stats times these weights (section 4).
- **`settings`, verified fields we use or may want:**
  - League type: `type` (2 = dynasty), `num_teams`
  - Rookie draft and taxi: `draft_rounds`, `taxi_slots`, `taxi_years`, `taxi_allow_vets`, `taxi_deadline`
  - Roster spots: `reserve_slots` (IR spots, 0 here), `reserve_allow_out` and the other `reserve_allow_*` rules
  - Trades: `pick_trading`, `trade_deadline` (week 11), `trade_review_days`
  - Playoffs: `playoff_teams` (6), `playoff_week_start` (15)
  - Waivers: `waiver_type` (2 = FAAB), `waiver_budget` (100), `waiver_bid_min`, `waiver_day_of_week`, `waiver_clear_days`
  - Scoring progress: `last_scored_leg` (last week with final scores)
- **`metadata`:** small league options such as `auto_continue` and `matchup_challenges`.
- **Chat fields** (`last_message_*`, `last_author_*`) only say when the last message was posted. The messages
  themselves aren't available.

**`GET /league/{league_id}/users`** lists the league's members.

- Each has `user_id`, `display_name`, `avatar`, `is_owner` (the commissioner flag) and `metadata.team_name`.
- `metadata.avatar` is a custom team image URL.

**`GET /league/{league_id}/rosters`** lists the rosters.

- **Players:** `roster_id`, `owner_id`, `co_owners`, `players` (everyone on the roster, taxi and IR included),
  `starters` (the current lineup, in `roster_positions` order), `reserve` (IR), `taxi`.
- **`settings`:** `wins`, `losses`, `ties`, `waiver_position`, `waiver_budget_used`, `total_moves`.
  - Points are split into a whole and a decimal part: `fpts` 818 + `fpts_decimal` 36 = 818.36 points for. The same
    goes for `fpts_against` and `ppts` (max potential points, the best possible lineup's score).
- **`metadata`:** `record` (`"LWWWLL"`) and `streak` (`"2L"`).
- A `keepers` field also appears.

**`GET /league/{league_id}/matchups/{week}`** returns one entry per roster.

- **Fields:** `roster_id`, `matchup_id` (the two rosters that play each other share it), `points`, `starters`,
  `starters_points` (same order), `players`, `players_points` ({player_id: points} for **every** rostered player,
  bench included), and `custom_points` (a commissioner override, usually `null`).
- **These are the league's own scores, so they're the ground truth for our scoring.** `points.check_scoring` compares
  against them every refresh. Weeks 1 to 6 matched our scoring on all 1,101 skill-player rows.
- **Before a week's games, it already returns entries with `points` 0** (verified, week 7). After the last week it
  returns `[]` (week 19).
- `players_points` includes kickers and defenses. Win-now doesn't count those slots, which explains about 17 points a
  week of the gap between win-now and actual team totals.

**`GET /league/{league_id}/winners_bracket`** and **`GET /league/{league_id}/losers_bracket`** return playoff
brackets.

- Each match has `r` (round), `m` (match number), `t1`/`t2` (roster IDs), `w`/`l` (winner and loser, `null` until
  played), `t1_from`/`t2_from` (which earlier match feeds each slot, like `{"w": 1}`), and `p` (the place it decides,
  such as 1st or 3rd).
- They already exist mid-season, seeded from the current standings (verified: 7 winners-bracket and 4 losers-bracket
  matches).
- The docs spell it `loses_bracket` in one place; `losers_bracket` is what works.

**`GET /league/{league_id}/transactions/{week}`** lists that week's moves. The docs call the parameter `round`, but it
is the week.

- **`type`:** `trade`, `waiver`, `free_agent`.
- **`status`:** `complete` (verified). `failed` for a lost waiver claim is reported but wasn't seen here.
- **What moved:** `adds` and `drops` ({player_id: roster_id}), `draft_picks` (picks traded), `waiver_budget` (FAAB
  traded).
- **Who:** `roster_ids` (rosters involved), `creator` (user ID), `consenter_ids`.
- **When and how much:** `created` and `status_updated` (milliseconds since epoch), `settings.waiver_bid` (the FAAB
  bid), `leg` (the week).
- **Week 0 returns `[]`** (verified). Offseason moves are filed under week 1.

**`GET /league/{league_id}/traded_picks`** lists only the picks that changed hands, future seasons included.

- Each has `season`, `round`, `roster_id` (the original owner), `owner_id` (the current owner) and `previous_owner_id`.
  All three are roster IDs, not user IDs.
- Untraded picks don't appear. `League.__init__` generates every team's own picks and then applies these trades.

### Drafts

**`GET /league/{league_id}/drafts`** lists the league's drafts, newest first: `draft_id`, `type` (`snake`, `linear`,
`auction`), `status`, `season`, `start_time` and `settings`.

- `settings` has `rounds`, `pick_timer` and `slots_*`, the roster slots used for drafting.

**`GET /draft/{draft_id}`** returns the same draft plus two maps:

- `draft_order`: {user_id: slot}.
- `slot_to_roster_id`: {slot: roster_id}. It gives exact pick positions once the order is set.

**`GET /draft/{draft_id}/picks`** lists every pick made.

- Fields: `player_id`, `picked_by` (user ID), `roster_id`, `round`, `draft_slot`, `pick_no` and `is_keeper`.
- `metadata` holds the player's name, position, team and status at the time of the pick.
- Verified: 230 picks in this league's startup draft.

**`GET /draft/{draft_id}/traded_picks`** works like the league endpoint, but only covers that one draft.

### Players

**`GET /players/nfl`** returns every NFL player as one map, {player_id: player}: about 5MB and 12,229 players.
Optional filters: `?position=` and `?active=true`.

- **Call it at most once a day and save it.** We save it to `data/sleeper_players.json`.
- **Fields on each player (verified from our saved copy):**
  - **Identity:** `full_name`, `first_name`, `last_name`, `position`, `fantasy_positions`, `team`, `number`, `age`,
    `birth_date`, `years_exp`, `college`, `height`, `weight`, `active`, `status`
  - **Injury and practice:** `injury_status`, `injury_body_part`, `injury_notes`, `injury_start_date`,
    `practice_participation`, `practice_description`
  - **Depth chart:** `depth_chart_position`, `depth_chart_order`
  - **Popularity:** `search_rank` (Sleeper's popularity order)
  - **Recency:** `news_updated`, `team_changed_at`
  - **Cross-site IDs:** `espn_id`, `yahoo_id`, `gsis_id`, `sportradar_id`, `rotowire_id`, `rotoworld_id`,
    `fantasy_data_id`, `stats_id`, `swish_id`, `opta_id`, `oddsjam_id`, `kalshi_id`, `pandascore_id`
- `gsis_id` is unreliable: it matched only 63 of 313 players. Join nflverse data through the DynastyProcess crosswalk
  instead (`ids.sleeper_id_from`).

**`GET /players/nfl/trending/{add|drop}?lookback_hours=24&limit=25`** returns the most-added or most-dropped players
across all Sleeper leagues.

- Each item is `{player_id, count}`.
- **Results are capped at 100** (verified: `limit=200` returned 100).
- **Counts are platform-wide:** 1.2 million adds for the top player over 24 hours.
- Sleeper asks for attribution when this data is shown.

### Images (not API calls)

- **Avatars:** `https://sleepercdn.com/avatars/{avatar_id}`, and `/avatars/thumbs/{avatar_id}` for a thumbnail.
- **Player headshots:** `https://sleepercdn.com/content/nfl/players/{player_id}.jpg` (reported).

---

## 4. Undocumented endpoints (no `/v1`)

These all worked on both `api.sleeper.app` and `api.sleeper.com`. `points.py` uses `api.sleeper.com`, the host
Sleeper's own app uses.

### Stats and projections

These endpoints matter most for this app. Stats and projections share the same paths: swap `stats` for `projections`.

| Call | Returns | Size |
|---|---|---|
| `GET /stats/nfl/{season}/{week}?season_type=regular&position[]=QB&position[]=RB&...` | Every player's line for one week, as a list | ~690KB for all six positions, 698 rows (week 6) |
| `GET /projections/nfl/{season}/{week}?season_type=regular&position[]=...` | Every player's projection for one week | ~2MB, 3,302 rows (week 7) |
| `GET /stats/nfl/{season}?season_type=regular&position[]=WR` | Season-to-date totals, one row per player | ~880KB for WR |
| `GET /projections/nfl/{season}?season_type=regular&position[]=WR` | Full-season projection (see quirks) | ~1.3MB for WR |
| `GET /stats/nfl/player/{player_id}?season_type=regular&season=2026` | One player's season totals | ~1.7KB |
| `GET /stats/nfl/player/{player_id}?season_type=regular&season=2026&grouping=week` | One player's stats by week: {"1": line, ..., "18": line or null} | ~5.5KB |
| `GET /projections/nfl/player/{player_id}?season_type=regular&season=2026&grouping=week` | One player's weekly projections, all 18 weeks | ~13KB |

All verified. Notes:

- **Without `position[]`** the stats call returns every player, offensive linemen and defensive players included:
  2,103 rows and about 1.9MB. Always filter by position.
- **`order_by=pts_ppr` trims the list** to players with a score (256 WR rows instead of about 1,364). We didn't check
  whether it also sorts.
- **`season_type=post`** returns playoff weeks (2025 postseason week 1 had 33 QB rows). Seasons go back at least to
  2017 (verified for 2017 and 2020).
- **Adding `&week=6`** to the per-player path returns `null`. To get one week, use `grouping=week` instead.
- **Each row has:**
  - Who and when: `player_id`, `week`, `season`, `date`, `team`, `opponent`, `game_id`
  - The numbers: `stats` (keyed by scoring key), `category` (`stat` or `proj`)
  - Freshness and source: `last_modified`, `updated_at`, `company` (`sportradar` for stats, `rotowire` reported for
    projections)
  - `player`: a small player summary with name, position, team and injury fields
- **`stats` keys are the league's `scoring_settings` keys.** So league points are the sum of stat times weight
  (`points.score`). The same object also carries:
  - `pts_ppr`, `pts_half_ppr` and `pts_std`: Sleeper's own totals. **Never use them:** they score an interception at
    -1, and this league uses -2.
  - Rank and ADP keys (`pos_rank_ppr`, `adp_dd_ppr`, `pos_adp_dd_ppr`) and detail stats (`rec_tgt`, `rec_fd`, yardage
    buckets like `rec_20_29`, `gms_active`, `gp`).
  - Rank and ADP keys don't match any scoring key, so they drop out of `points.score` by themselves.

**Quirks:**

- **The full-season projection still counts weeks already played** (`gp` 18). It is not a rest-of-season figure. Sum
  the remaining weekly projections instead, as `points.pull` does.
- **Byes still get a weekly projection row**, with `opponent: null` and only ADP keys in `stats`. Filter on
  `opponent`.
- **A player who didn't play has no stats row that week.** In `grouping=week` that week is `null`, which is how Gibbs's
  week 6 bye shows up. Treat a missing row as 0, not as an error.
- **Past weekly projections aren't guaranteed to be the pre-game numbers.** Every week 1 projection has
  `last_modified` of 2026-09-15, after that week's last game. Week 3 is dated 2026-09-29 and week 6 2026-10-20, the
  same pattern.
  - Sleeper re-touches projections after the games. Whether the numbers themselves change is unknown.
  - **To measure projection accuracy, save each week's projection before kickoff ourselves.** Don't re-download it
    later.
- **Stats change after games.** The NFL issues stat corrections through Wednesday, so a week's stats are final on
  Thursday. `points.check` checks the week before last on Tuesday and Wednesday for this reason.
- **The legacy path works again:** `api.sleeper.app/v1/projections/nfl/regular/{season}/{week}` and
  `/v1/stats/nfl/regular/{season}/{week}` return a map {player_id: stats} with no player info, no opponent and no
  `last_modified` (verified).
  - It was reported empty in September 2026, which is why `points.py` uses the newer path.
  - Keep using the newer path. It carries `opponent`, which byes are filtered on.

**Week-by-week scores for every player:** one bulk call per finished week (`/stats/nfl/2026/{w}` with positions)
returns everyone's stats that week. Weeks 1 to 6 is 6 calls. Score each row with `points.score` to get league points.
The per-player `grouping=week` call does the same job but costs one call per player, about 700. Use the bulk call.

### Schedule

**`GET /schedule/nfl/regular/{season}`** returns all 272 regular-season games (verified):

```json
{"status": "complete", "date": "2026-09-13", "home": "CAR", "away": "CHI", "week": 1, "game_id": "202610105"}
```

- **`status`:** we saw `complete` and, in the 2025 postseason, `canceled`. Values for games not yet played or in
  progress weren't checked.
- **`game_id`** matches `game_id` on stats rows.
- **Team codes** match the player data.
- **Bye weeks are the weeks a team doesn't appear in.** This is the source if we ever need each player's bye week.
- **`/schedule/nfl/post/{season}`** returns playoff games, with `TBD` until a matchup is set.

### Depth charts

**`GET /players/nfl/{TEAM}/depth_chart`** maps each position to player IDs in depth order (verified for DET).

```json
{"QB": ["3163", "4179"], "RB": ["9221", "11729", ...], "WR1": ["7547"], "WR2": [...], "WR3": [...], "TE": [...]}
```

- Receivers are split into `WR1`, `WR2` and `WR3` slots. Defense, kicker and offensive line keys come too.
- `depth_chart_position` and `depth_chart_order` on each player say the same thing.

### Single player

**`GET /players/nfl/{player_id}`** returns one player's entry from the full database, about 1KB and cached for 10
minutes (verified). Use it to refresh one player mid-day without downloading 5MB.

### Player news

**`GET /players/nfl/{player_id}/news?limit=N`** returns recent news items for one player (verified). It returned 5 by
default and 10 with `limit=20`.

- Each item has `source` (for example `fantasy_pros`), `published` (milliseconds since epoch), `player_id`,
  `source_key`, and `metadata`, which holds the text (`analysis`, title, and so on).
- **No community client lists this endpoint.** Assume it is the least stable of the group.
- `/v1/players/nfl/news` returns 404, so there is no league-wide news feed.

### Ownership and start rates

**`GET /players/nfl/research/{regular|post}/{season}/{week}`** returns, for each player, the share of Sleeper leagues
that roster and start them: {player_id: {"owned": 97.3, "started": 95.7}} (verified).

- **Adding `?league_type=2` changes the result** (1,575 players instead of 712). This is likely dynasty-only
  ownership, because 2 is the dynasty `settings.type`; that's our reading, not confirmed.
- **It's useful for waivers:** a player owned in few leagues but started where rostered is a likely breakout.

### Reported but not tested

- **GraphQL `stats_for_players_in_week`** on `https://sleeper.com/graphql`: stats or projections for a list of player
  IDs ([joeyagreco/sleeper discussion #11](https://github.com/joeyagreco/sleeper/discussions/11)). Not needed; the
  REST endpoints cover it.

---

## 5. What exists only as a side effect, and what doesn't exist

**Not available from any endpoint we found:**

- **League standings.** `/v1/league/{id}/standings` returns 404. Compute them from roster `settings` (wins, losses,
  `fpts`).
- **League chat messages.** Only the last-message timestamp on the league is public.
- **Matchup schedule for future weeks.** Each week's `matchup_id` pairings appear in `/matchups/{week}` once that week
  is current, with `points` 0.
- **Odds and live in-game scoring as its own feed.** During games `/matchups/{week}` updates (60s cache) and stats
  rows update. Nothing else gives live scoring.

**Things that look like errors but aren't:** an empty list `[]` means "nothing yet", not a failure. This applies to
matchups past week 18, transactions in week 0, and draft traded picks after the draft.

---

## 6. Write access (lineups, waivers, trades): not for this project

The public API is read-only by design: "No API Token is necessary, as you cannot modify contents via this API"
([docs.sleeper.com](https://docs.sleeper.com/)).

- **Sleeper's app does write through `https://sleeper.com/graphql`**, using a logged-in session token. Community
  projects use it to set lineups, move players to IR or taxi, add and drop players, place and cancel waiver claims,
  propose and answer trades, and post to league chat
  ([alexepner/sleeper-mcp](https://github.com/alexepner/sleeper-mcp)).
- **That means handling your Sleeper password or session token.** It's undocumented and unsupported, and it acts on
  your real account.
- **This project stays read-only.** Ledger values trades and suggests moves; you make them in the Sleeper app.

---

## 7. What this project uses today

| Endpoint | Where |
|---|---|
| `/v1/state/nfl` | `points.py` (week and season) |
| `/v1/league/{id}`, `/users`, `/rosters`, `/traded_picks`, `/drafts` | `league.fetch` |
| `/v1/league/{id}/matchups/{week}` | `points.check_scoring` |
| `/v1/players/nfl` (once a day) | `ids.sleeper_players` |
| `/stats/nfl/{season}/{week}` | `points.pull` (last week), `points.check`, `points.check_scoring` |
| `/projections/nfl/{season}/{week}`, this week through week 18 | `points.pull` (rest of season) |

**Unused, in rough order of value:**

1. **Weekly stats for every past week:** a per-week points history (6 calls).
2. **Projection snapshots saved before kickoff:** the only way to measure projection accuracy (section 4 quirks).
3. **`/schedule`:** real bye weeks.
4. **`/players/nfl/research`:** an ownership signal for waivers.
5. **`/transactions/{week}`:** a league trade and waiver log, and FAAB spent.
6. **`/players/nfl/trending`:** what's hot across Sleeper.
7. **`/players/nfl/{id}/news`:** a news blurb next to a player.
8. **Depth charts:** role changes (a backup becoming the starter).
9. **Brackets:** playoff odds.

---

## Sources

- Sleeper's official docs: [docs.sleeper.com](https://docs.sleeper.com/)
- Undocumented endpoint list: [joeyagreco/sleeper, discussion #11](https://github.com/joeyagreco/sleeper/discussions/11)
- Go client with research, schedule and depth-chart paths: [lum8rjack/sleeper-go](https://pkg.go.dev/github.com/lum8rjack/sleeper-go)
- GraphQL write tools and rate-limit practice: [alexepner/sleeper-mcp](https://github.com/alexepner/sleeper-mcp)
- Report of the `v1/projections` path going empty: [allenheltondev/ai-fantasy-league #184](https://github.com/allenheltondev/ai-fantasy-league/issues/184)
- Live tests: `sources/common.sleeper_get`, 2026-10-22, league `1395495049021652992`
