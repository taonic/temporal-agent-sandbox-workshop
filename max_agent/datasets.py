"""Datasets Max analyzes, and the working copy runs use.

Each dataset lives in datasets/<name>/: a standalone generate.py (the source
of truth), committed CSVs and a README. Runs never touch the committed files:
they use a working copy in settings.data_dir, where "new data" appends days.

    uv run python -m max_agent.datasets reset   # fresh working copy from the committed CSVs
"""

import importlib.util
import shutil
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

from max_agent.config import ROOT, Settings, settings

DATASETS_DIR = ROOT / "datasets"


@cache
def generator(name: str) -> ModuleType:
    path = DATASETS_DIR / name / "generate.py"
    spec = importlib.util.spec_from_file_location(f"dataset_{name.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tables(s: Settings = settings) -> list[str]:
    return list(generator(s.dataset).TABLES)


def working_copy(s: Settings = settings, reset: bool = False) -> Path:
    """The directory runs read from, seeded from the committed CSVs on first use."""
    target = s.data_dir
    marker = target / ".dataset"
    if reset or not marker.exists() or marker.read_text() != s.dataset:
        target.mkdir(parents=True, exist_ok=True)
        for table in tables(s):
            shutil.copyfile(DATASETS_DIR / s.dataset / f"{table}.csv", target / f"{table}.csv")
        marker.write_text(s.dataset)
    return target


def day_count(s: Settings = settings) -> int:
    return generator(s.dataset).day_count(working_copy(s))


def append_day(s: Settings = settings) -> str:
    """Drop in tomorrow's data (every daily table). Returns the new date."""
    return generator(s.dataset).append_day(working_copy(s))


def write_working_copy(s: Settings, days: int) -> Path:
    """Tests: a smaller working copy generated directly (no committed files involved)."""
    generator(s.dataset).write(s.data_dir, days=days)
    (s.data_dir / ".dataset").write_text(s.dataset)
    return s.data_dir


if __name__ == "__main__":
    if sys.argv[1:] == ["reset"]:
        path = working_copy(reset=True)
        print(f"fresh working copy of {settings.dataset!r} in {path} ({day_count()} days)")
    else:
        sys.exit(__doc__)
