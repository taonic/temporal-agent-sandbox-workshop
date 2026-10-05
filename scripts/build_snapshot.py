"""Build the Daytona snapshot Max's sandboxes start from. Run once per Daytona org.

    uv run python scripts/build_snapshot.py [--force]

Pre-installing pandas and matplotlib means a sandbox is ready in seconds,
instead of every learner pip-installing at the same time.
"""

import argparse
import asyncio

from daytona import AsyncDaytona, CreateSnapshotParams, DaytonaNotFoundError, Image, Resources

from max_agent.config import settings


async def main(force: bool) -> None:
    name = settings.daytona_snapshot
    async with AsyncDaytona() as daytona:
        try:
            existing = await daytona.snapshot.get(name)
            if not force:
                print(f"snapshot {name!r} already exists ({existing.state}); use --force to rebuild")
                return
            await daytona.snapshot.delete(existing)
            print(f"deleted old snapshot {name!r}")
        except DaytonaNotFoundError:
            pass

        image = (
            Image.debian_slim("3.12")
            .pip_install("pandas==2.3.3", "matplotlib==3.10.7")
            .env({"MPLBACKEND": "Agg"})
        )
        print(f"building snapshot {name!r} (a few minutes)...")
        await daytona.snapshot.create(
            CreateSnapshotParams(name=name, image=image, resources=Resources(cpu=1, memory=1, disk=3)),
            on_logs=lambda line: print("  ", line),
            timeout=0,
        )
        print(f"snapshot {name!r} ready")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    asyncio.run(main(p.parse_args().force))
