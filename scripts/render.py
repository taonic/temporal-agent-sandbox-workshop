"""Render learner code from the authoring masters.

Files under authoring/ hold both the solution and the starter for each
challenge, between markers:

    # @@solution ch02
    ...code learners write in challenge 2...
    # @@starter
    ...what they start with (a TODO)...
    # @@end

`render.py` writes:
    max_agent/...           stage 0: every TODO open (what learners start with)
    solutions/chNN/...      stage N: challenges 1..N solved

Usage:
    uv run python scripts/render.py            # write everything
    uv run python scripts/render.py --check    # fail if outputs are stale (CI)
    uv run python scripts/render.py --stage 4 --out max_agent   # dev: fully solved in place
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTHORING = ROOT / "authoring"
CHAPTERS = 4
MARKER = re.compile(r"^\s*# @@(solution ch(\d+)|starter|end)\s*$")


def render(text: str, stage: int) -> str:
    out, mode, chapter = [], None, 0
    for line in text.splitlines(keepends=True):
        m = MARKER.match(line)
        if m:
            if m.group(1).startswith("solution"):
                mode, chapter = "solution", int(m.group(2))
            elif m.group(1) == "starter":
                mode = "starter"
            else:
                mode = None
            continue
        if mode is None or (mode == "solution") == (chapter <= stage):
            out.append(line)
    return "".join(out)


def outputs(stage_dirs: dict[int, Path]) -> dict[Path, str]:
    files = {}
    for master in sorted(AUTHORING.rglob("*.py")):
        rel = master.relative_to(AUTHORING)
        text = master.read_text()
        for stage, base in stage_dirs.items():
            files[base / rel] = render(text, stage)
    return files


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.add_argument("--stage", type=int)
    p.add_argument("--out", type=Path)
    args = p.parse_args()

    if args.stage is not None:
        # The authoring tree mirrors the repo root, so rendered files land under --out's parent.
        targets = {args.stage: (args.out or ROOT).resolve()}
        if targets[args.stage].name == "max_agent":
            targets[args.stage] = targets[args.stage].parent
    else:
        targets = {0: ROOT, **{n: ROOT / "solutions" / f"ch{n:02d}" for n in range(1, CHAPTERS + 1)}}

    stale = []
    for path, content in outputs(targets).items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(path.relative_to(ROOT))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        sys.exit("stale rendered files (run scripts/render.py):\n  " + "\n  ".join(map(str, stale)))


if __name__ == "__main__":
    main()
