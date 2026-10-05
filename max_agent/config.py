"""Environment-driven settings.

Only processes (worker, web app, scripts) read the environment. Workflows never
do: anything a workflow needs is copied into its input when it starts, so a
replay months later sees exactly the same values.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env support: KEY=value lines; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    temporal_address: str = field(default_factory=lambda: os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))
    temporal_namespace: str = field(default_factory=lambda: os.environ.get("TEMPORAL_NAMESPACE", "default"))
    task_queue: str = field(default_factory=lambda: os.environ.get("TASK_QUEUE", "max"))
    # Where a *browser* reaches the Temporal UI (differs from localhost behind Instruqt's proxy).
    temporal_ui_url: str = field(default_factory=lambda: os.environ.get("TEMPORAL_UI_URL", "http://localhost:8233"))

    # LLM: "openai" talks to any OpenAI-compatible endpoint (Ollama by default);
    # "scripted" replays a canned plan so checks and offline runs are deterministic.
    llm_mode: str = field(default_factory=lambda: os.environ.get("LLM_MODE", "openai"))
    llm_base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1"))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "qwen3.5:4b"))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", "ollama"))

    # Sandboxes
    sandbox_provider: str = field(default_factory=lambda: os.environ.get("SANDBOX_PROVIDER", "daytona"))
    daytona_snapshot: str = field(default_factory=lambda: os.environ.get("DAYTONA_SNAPSHOT", "max-analyst-py"))
    learner_id: str = field(default_factory=lambda: os.environ.get("LEARNER_ID", os.environ.get("USER", "local")))

    # Timing (seconds) and limits
    idle_timeout_s: int = field(default_factory=lambda: _int("IDLE_TIMEOUT_S", 60))
    approval_timeout_s: int = field(default_factory=lambda: _int("APPROVAL_TIMEOUT_S", 180))
    max_steps: int = field(default_factory=lambda: _int("MAX_STEPS", 8))
    max_parallel: int = field(default_factory=lambda: _int("MAX_PARALLEL", 3))

    # Which datasets/<name>/ Max analyzes, and where runs keep their working copy of it.
    dataset: str = field(default_factory=lambda: os.environ.get("DATASET", "coffee-chain"))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", ROOT / "data")))
    artifacts_dir: Path = field(default_factory=lambda: Path(os.environ.get("ARTIFACTS_DIR", ROOT / "artifacts")))


settings = Settings()
