"""The datasets: committed CSVs match their generator, and runs never modify them."""

import csv
from dataclasses import replace

from max_agent import config
from max_agent.datasets import DATASETS_DIR, append_day, day_count, generator, tables, working_copy


def test_committed_csvs_match_generator():
    assert generator("coffee-chain").stale() == [], "run: python datasets/coffee-chain/generate.py"


def test_new_data_goes_to_the_working_copy_only(tmp_path):
    s = replace(config.settings, data_dir=tmp_path / "data")
    committed = {t: (DATASETS_DIR / "coffee-chain" / f"{t}.csv").read_text() for t in tables(s)}

    assert day_count(s) == 60
    assert append_day(s) == "2026-09-30"
    assert append_day(s) == "2026-10-01"
    assert day_count(s) == 62
    assert {t: (DATASETS_DIR / "coffee-chain" / f"{t}.csv").read_text() for t in tables(s)} == committed

    working_copy(s, reset=True)
    assert day_count(s) == 60


def test_planted_stories_and_defects():
    rows = list(csv.DictReader((DATASETS_DIR / "coffee-chain" / "sales.csv").open()))
    assert any(r["store"] == "Soma" for r in rows), "misspelled store"
    assert any(float(r["revenue"]) < 0 for r in rows), "refund"
    sunset_days = {r["date"] for r in rows if r["store"] == "Sunset"}
    assert len(sunset_days) == 58, "two days of Sunset sales missing"
    keys = [tuple(r.values()) for r in rows]
    assert len(keys) - len(set(keys)) == 8, "Mission's duplicated export"

    stockouts = [r for r in csv.DictReader((DATASETS_DIR / "coffee-chain" / "inventory.csv").open()) if r["stockout"] == "True"]
    assert {r["store"] for r in stockouts} == {"Castro"} and len(stockouts) == 7
