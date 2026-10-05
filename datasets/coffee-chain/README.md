# Coffee-chain dataset

This is synthetic data for a five-store San Francisco coffee chain, covering 60 days from 2026-08-01 to 2026-09-29. It's seeded, so day N is always the same.

`generate.py` is the source of truth. After changing it, regenerate the CSVs with `python datasets/coffee-chain/generate.py`; `tests/test_datasets.py` fails if the CSVs are out of date.

Runs never modify these files. Max works on a copy in `data/` (`DATA_DIR`), and "Drop in tomorrow's sales" appends a day to every daily table there. To start over, run `uv run python -m max_agent.datasets reset`.

## Tables

Inside the sandbox, every script starts with these tables loaded as pandas DataFrames (see `PREAMBLE` in `max_agent/agent/prompts.py`).

| Table | Rows | Columns | Grain |
|---|---|---|---|
| `sales` (also `df`) | ~2,400 | `date, store, drink, weather, qty, revenue` | store × drink × day |
| `promotions` | 3 | `promo_id, store, drink, start, end, discount_pct, days` | one row per promotion; `days` is `every day` or `weekends` |
| `shifts` | 300 | `date, store, staff_hours, labor_cost` | store × day |
| `inventory` | 900 | `date, store, item, unit, received, wasted, stockout` | store × item × day; items: oat milk (L), cold brew concentrate (L), espresso beans (kg) |

Stores: Mission, SoMa, Castro, Sunset, Marina. Join on `date` and `store`, and also on `drink` for promotions.

## Planted stories

These are things a good analysis should find. Use them to judge Max's answers.

| Story | Where it shows | Numbers (approx.) |
|---|---|---|
| Castro's Matcha Latte takes off in the last two weeks | `sales` | from 2026-09-16: about 2×, rising to about 3× normal cups |
| Castro's oat milk runs out, then overshoots | `inventory` | stockouts on 2026-09-16 to 09-22; then waste ~6 L/day instead of ~0.5 |
| Rain hurts Cold Brew everywhere | `sales` | cups ~65% lower on rainy days |
| Sunset (the foggy one) wastes cold brew concentrate on rainy days | `inventory` | ~3.5 L/day wasted when rainy, ~0.6 otherwise |
| SoMa is a weekday office crowd | `sales` | weekend sales about half of weekday |
| SoMa is overstaffed at weekends | `shifts` + `sales` | labor ≈ 61% of revenue at weekends, ~30% elsewhere |
| Marina is busiest at weekends | `sales`, `shifts` | |
| Mission's 30%-off Cold Brew promo (P2) sold more cups but made less money | `promotions` + `sales` | +18% cups, −17% revenue per day |
| Marina's weekend Mocha promo (P3) paid off | `promotions` + `sales` | weekend Mocha revenue up ~48% |
| SoMa's 15%-off Latte promo (P1) barely moved anything | `promotions` + `sales` | |

## Deliberate defects

Real data is messy, and spotting the mess is part of the job. The preamble does **not** clean anything.

| Defect | Where |
|---|---|
| Sunset's sales missing (POS outage); its shifts still recorded | `sales`, 2026-08-21 and 08-22 |
| Mission's rows exported twice | `sales`, 2026-09-03 (8 duplicate rows) |
| SoMa spelled `Soma` by a new POS terminal | `sales`, 2026-09-10 to 09-14 |
| A refund recorded as a negative sale (Latte, −40 cups, −$210) | `sales`, Castro, 2026-09-17 |
| One mistake every third day of *new* data, rotating between duplicated Marina rows, `Soma`, and missing Sunset sales | days appended to the working copy |

A careful answer to "which store sold the most?" notices `Soma`. A careful answer about a single day notices duplicates and gaps.
