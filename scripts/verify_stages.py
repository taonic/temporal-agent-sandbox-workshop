"""Prove every TODO matters and every solution works.

For each stage N (0 = starter, 4 = all solved), render the code into a temp
copy and run each challenge's check. Challenge K's check must pass exactly
when K <= N. The provided-code tests (test_sandbox.py) must always pass.

    uv run python scripts/verify_stages.py
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render import CHAPTERS, ROOT, outputs  # noqa: E402

CHECKS = {
    0: "tests/test_sandbox.py",
    1: "tests/test_ch01_meet_max.py",
    2: "tests/test_ch02_idle_suspend.py",
    3: "tests/test_ch03_approval.py",
    4: "tests/test_ch04_team.py",
}


def build(stage: int) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=f"max-stage{stage}-"))
    shutil.copytree(ROOT / "max_agent", tmp / "max_agent", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "tests", tmp / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "datasets", tmp / "datasets", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "pyproject.toml", tmp / "pyproject.toml")
    for path, content in outputs({stage: tmp}).items():
        path.write_text(content)
    return tmp


async def run_check(stage: int, tmp: Path, chapter: int) -> tuple[int, int, bool]:
    # PYTHONPATH puts the rendered copy ahead of the repo's editable install.
    env = {**os.environ, "PYTHONPATH": str(tmp)}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", CHECKS[chapter],
        cwd=tmp, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    return stage, chapter, await proc.wait() == 0


async def main() -> None:
    dirs = {stage: build(stage) for stage in range(CHAPTERS + 1)}
    jobs = [run_check(stage, tmp, ch) for stage, tmp in dirs.items() for ch in CHECKS]
    results = await asyncio.gather(*jobs)
    ok = True
    print("stage  " + "  ".join(f"ch{c:02d}" if c else "base" for c in CHECKS))
    table = {(s, c): passed for s, c, passed in results}
    for stage in dirs:
        cells = []
        for ch in CHECKS:
            passed, expected = table[(stage, ch)], ch <= stage
            ok &= passed == expected
            cells.append(("pass" if passed else "FAIL") + (" " if passed == expected else "!"))
        print(f"  {stage}    " + " ".join(cells))
    for tmp in dirs.values():
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nall stages behave as expected" if ok else "\n'!' marks a check that didn't match its stage")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
