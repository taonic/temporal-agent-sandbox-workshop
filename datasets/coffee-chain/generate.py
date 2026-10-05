"""Coffee-chain dataset: four tables, seeded and deterministic (day N is always the same).

    python datasets/coffee-chain/generate.py          # rewrite the committed CSVs
    python datasets/coffee-chain/generate.py --check  # fail if they are stale

Standalone on purpose (standard library only): it is the source of truth for
the CSVs next to it. See README.md for the schema, planted stories and defects.
"""

import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
START = date(2026, 8, 1)
INITIAL_DAYS = 60
TABLES = ["sales", "promotions", "shifts", "inventory"]
FIELDS = {
    "sales": ["date", "store", "drink", "weather", "qty", "revenue"],
    "promotions": ["promo_id", "store", "drink", "start", "end", "discount_pct", "days"],
    "shifts": ["date", "store", "staff_hours", "labor_cost"],
    "inventory": ["date", "store", "item", "unit", "received", "wasted", "stockout"],
}

STORES = {"Mission": 1.0, "SoMa": 1.15, "Castro": 0.85, "Sunset": 0.7, "Marina": 0.95}
DRINKS = {  # drink: (price, base cups/day)
    "Latte": (5.25, 60),
    "Cappuccino": (4.95, 35),
    "Americano": (3.95, 40),
    "Cold Brew": (5.50, 45),
    "Matcha Latte": (5.75, 20),
    "Mocha": (5.65, 18),
    "Chai": (5.10, 22),
    "Espresso": (3.25, 25),
}
BASE_STAFF_HOURS = {"Mission": 16, "SoMa": 20, "Castro": 13, "Sunset": 11, "Marina": 15}
HOURLY_RATE = 26.0
MATCHA_SURGE_DAY = INITIAL_DAYS - 14  # Castro's matcha takes off here
OAT_MILK_RESTOCK_DAY = MATCHA_SURGE_DAY + 7  # ...and oat milk orders catch up (then overshoot) here

# Promotions: (id, store, drink, first day index, last day index, discount %, days, qty multiplier)
PROMOTIONS = [
    ("P1", "SoMa", "Latte", 10, 16, 15, "every day", 1.1),
    ("P2", "Mission", "Cold Brew", 24, 37, 30, "every day", 1.25),  # more cups, less revenue
    ("P3", "Marina", "Mocha", 38, 59, 20, "weekends", 1.8),  # pays off
]


def day_date(i: int) -> date:
    return START + timedelta(days=i)


def weather(i: int, store: str) -> str:
    rng = random.Random(f"weather-{i}-{store}")
    rain = 0.35 if store == "Sunset" else 0.18
    r = rng.random()
    return "rainy" if r < rain else "cloudy" if r < rain + 0.3 else "sunny"


def active_promo(i: int, store: str, drink: str):
    weekend = day_date(i).weekday() >= 5
    for p in PROMOTIONS:
        pid, p_store, p_drink, first, last, pct, days, mult = p
        if p_store == store and p_drink == drink and first <= i <= last and (days == "every day" or weekend):
            return pct, mult
    return None


def sales_rows(i: int) -> list[dict]:
    rng = random.Random(f"sales-{i}")
    d = day_date(i)
    weekend = d.weekday() >= 5
    rows = []
    for store, size in STORES.items():
        w = weather(i, store)
        mood = size
        if store == "SoMa":
            mood *= 0.55 if weekend else 1.1
        if store == "Marina":
            mood *= 1.35 if weekend else 0.9
        for drink, (price, base) in DRINKS.items():
            mult = mood
            if drink == "Cold Brew":
                mult *= {"sunny": 1.4, "cloudy": 1.0, "rainy": 0.45}[w]
            if drink in ("Mocha", "Chai") and w == "rainy":
                mult *= 1.3
            if drink == "Matcha Latte" and store == "Castro" and i >= MATCHA_SURGE_DAY:
                mult *= min(3.5, 2.2 + 0.08 * (i - MATCHA_SURGE_DAY))
            unit_price = price
            if promo := active_promo(i, store, drink):
                pct, promo_mult = promo
                unit_price = price * (1 - pct / 100)
                mult *= promo_mult
            qty = max(0, round(rng.gauss(base * mult, base * mult * 0.12)))
            rows.append({"date": d.isoformat(), "store": store, "drink": drink, "weather": w,
                         "qty": qty, "revenue": round(qty * unit_price, 2)})
    return rows


def shift_rows(i: int) -> list[dict]:
    rng = random.Random(f"shifts-{i}")
    weekend = day_date(i).weekday() >= 5
    rows = []
    for store, base in BASE_STAFF_HOURS.items():
        hours = base
        if weekend:
            # Every store staffs up a little at weekends, Marina a lot. SoMa keeps its
            # weekday roster although its office crowd is gone: overstaffed.
            hours *= {"SoMa": 1.0, "Marina": 1.3}.get(store, 1.1)
        hours = round(hours + rng.uniform(-1, 1), 1)
        rows.append({"date": day_date(i).isoformat(), "store": store, "staff_hours": hours,
                     "labor_cost": round(hours * HOURLY_RATE, 2)})
    return rows


def inventory_rows(i: int) -> list[dict]:
    rng = random.Random(f"inventory-{i}")
    rows = []
    for store in STORES:
        w = weather(i, store)
        # Oat milk (L): Castro's matcha surge runs it out for a week, then the
        # catch-up orders overshoot and the surplus spoils.
        received, wasted, stockout = 8.0, rng.uniform(0.2, 0.8), False
        if store == "Castro" and MATCHA_SURGE_DAY <= i < OAT_MILK_RESTOCK_DAY:
            wasted, stockout = 0.0, True
        elif store == "Castro" and i >= OAT_MILK_RESTOCK_DAY:
            received, wasted = 22.0, rng.uniform(5.5, 8.0)
        rows.append({"item": "oat milk", "unit": "L", "received": received, "wasted": wasted, "stockout": stockout})
        # Cold brew concentrate (L) is made each morning; rain leaves it unsold, worst at Sunset.
        rain_waste = (3.0, 4.0) if store == "Sunset" else (1.2, 1.8)
        wasted = rng.uniform(*rain_waste) if w == "rainy" else rng.uniform(0.3, 0.9)
        rows.append({"item": "cold brew concentrate", "unit": "L", "received": 6.0, "wasted": wasted, "stockout": False})
        rows.append({"item": "espresso beans", "unit": "kg", "received": 3.0, "wasted": rng.uniform(0.0, 0.2), "stockout": False})
        for r in rows[-3:]:
            r.update(date=day_date(i).isoformat(), store=store, wasted=round(r["wasted"], 2))
    return [{k: r[k] for k in FIELDS["inventory"]} for r in rows]


def apply_defects(i: int, sales: list[dict]) -> list[dict]:
    """Real data is messy. These mistakes are deliberate; README.md lists them."""
    def rename_soma(rows):
        return [{**r, "store": "Soma"} if r["store"] == "SoMa" else r for r in rows]

    if i in (20, 21):  # POS outage: Sunset's sales never got exported
        return [r for r in sales if r["store"] != "Sunset"]
    if i == 33:  # export retried: Mission's rows appear twice
        return sales + [r for r in sales if r["store"] == "Mission"]
    if 40 <= i <= 44:  # new POS terminal spells the store "Soma"
        return rename_soma(sales)
    if i == 47:  # a refund recorded as a negative sale
        castro = next(r for r in sales if r["store"] == "Castro")
        return sales + [{**castro, "drink": "Latte", "qty": -40, "revenue": -210.0}]
    k = i - INITIAL_DAYS
    if k >= 0 and k % 3 == 2:  # every third day of new data carries one mistake
        kind = (k // 3) % 3
        if kind == 0:
            return sales + [r for r in sales if r["store"] == "Marina"]
        if kind == 1:
            return rename_soma(sales)
        return [r for r in sales if r["store"] != "Sunset"]
    return sales


def day_tables(i: int) -> dict[str, list[dict]]:
    """One day's rows for every daily table (promotions are a fixed schedule)."""
    return {"sales": apply_defects(i, sales_rows(i)), "shifts": shift_rows(i), "inventory": inventory_rows(i)}


def promotion_rows(days: int) -> list[dict]:
    return [
        {"promo_id": pid, "store": store, "drink": drink, "start": day_date(first).isoformat(),
         "end": day_date(last).isoformat(), "discount_pct": pct, "days": days_rule}
        for pid, store, drink, first, last, pct, days_rule, _ in PROMOTIONS
        if first < days
    ]


def build(days: int = INITIAL_DAYS) -> dict[str, list[dict]]:
    tables = {name: [] for name in TABLES}
    tables["promotions"] = promotion_rows(days)
    for i in range(days):
        for name, rows in day_tables(i).items():
            tables[name].extend(rows)
    return tables


def _csv_text(name: str, rows: list[dict]) -> str:
    import io

    buf = io.StringIO()
    w = csv.DictWriter(buf, FIELDS[name], lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def write(directory: Path, days: int = INITIAL_DAYS) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, rows in build(days).items():
        (directory / f"{name}.csv").write_text(_csv_text(name, rows))


def day_count(directory: Path) -> int:
    """Days in a copy of the dataset, from the shifts table (every store, every day)."""
    with (directory / "shifts.csv").open() as f:
        return len({row["date"] for row in csv.DictReader(f)})


def append_day(directory: Path) -> str:
    """Append tomorrow to every daily table in `directory`. Returns the new date."""
    i = day_count(directory)
    for name, rows in day_tables(i).items():
        with (directory / f"{name}.csv").open("a", newline="") as f:
            csv.DictWriter(f, FIELDS[name], lineterminator="\n").writerows(rows)
    return day_date(i).isoformat()


def stale(directory: Path = HERE) -> list[str]:
    return [
        f"{name}.csv"
        for name, rows in build().items()
        if not (directory / f"{name}.csv").exists() or (directory / f"{name}.csv").read_text() != _csv_text(name, rows)
    ]


if __name__ == "__main__":
    if "--check" in sys.argv:
        if bad := stale():
            sys.exit(f"stale: {', '.join(bad)} (run: python datasets/coffee-chain/generate.py)")
        print("coffee-chain CSVs are up to date")
    else:
        write(HERE)
        print(f"wrote {', '.join(f'{t}.csv' for t in TABLES)} ({INITIAL_DAYS} days) to {HERE}")
