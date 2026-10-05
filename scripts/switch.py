"""Switch max_agent/ between the finished Max (what the repo ships) and the starter code.

    uv run python scripts/switch.py starter    # challenge TODOs open, to do the workshop locally
    uv run python scripts/switch.py solution   # back to the finished Max
    uv run python scripts/switch.py status     # which one is in place?

Only the three files with challenge TODOs change. If you've edited them,
your version is copied to .learner-backup/<timestamp>/ before being replaced.
Restart the worker afterwards to load the new code.
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render import CHAPTERS, ROOT, outputs  # noqa: E402

STAGES = {"starter": 0, "solution": CHAPTERS}


def current_stage() -> int | None:
    """The stage max_agent/ matches exactly, or None if it has been edited."""
    for stage in range(CHAPTERS + 1):
        if all(p.exists() and p.read_text() == c for p, c in outputs({stage: ROOT}).items()):
            return stage
    return None


def describe(stage: int | None) -> str:
    if stage is None:
        return "edited by hand (in the middle of the challenges)"
    if stage == 0:
        return "starter code: all challenge TODOs open"
    if stage == CHAPTERS:
        return "the finished Max: all challenges solved"
    return f"challenges 1-{stage} solved"


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in (*STAGES, "status"):
        sys.exit(__doc__)
    stage = current_stage()
    if sys.argv[1] == "status":
        print(f"max_agent/ is {describe(stage)}.")
        return

    target = STAGES[sys.argv[1]]
    if stage == target:
        print(f"Already {describe(stage)}.")
        return
    files = outputs({target: ROOT})
    if stage is None:
        backup = ROOT / ".learner-backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
        for path in files:
            dest = backup / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        print(f"Your edits are saved in {backup.relative_to(ROOT)}/")
    for path, content in files.items():
        path.write_text(content)
    print(f"max_agent/ is now {describe(target)}.")
    print("Restart the worker (Ctrl-C, then: uv run max-worker) to load it.")


if __name__ == "__main__":
    main()
