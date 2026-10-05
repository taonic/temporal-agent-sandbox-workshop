"""Side effects Max has on the world outside its sandbox."""

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel
from temporalio import activity

from max_agent.agent.models import AnalysisResult
from max_agent.config import settings


class PublishRequest(BaseModel):
    post_id: str  # idempotency key: a retried publish must not post twice
    workflow_id: str
    result: AnalysisResult
    approved_by: str


def channel_path() -> Path:
    return settings.artifacts_dir / "channel.jsonl"


def read_channel() -> list[dict]:
    path = channel_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@activity.defn
async def publish_report(req: PublishRequest) -> None:
    """Post the report to the (pretend) #analytics channel."""
    if any(p["post_id"] == req.post_id for p in read_channel()):
        return  # already posted by an earlier attempt
    channel_path().parent.mkdir(parents=True, exist_ok=True)
    with channel_path().open("a") as f:
        f.write(
            json.dumps(
                {
                    "post_id": req.post_id,
                    "workflow_id": req.workflow_id,
                    "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "approved_by": req.approved_by,
                    **req.result.model_dump(),
                }
            )
            + "\n"
        )


class TeamReportRequest(BaseModel):
    path: str
    members: list[AnalysisResult]
    failed: list[str]


@activity.defn
async def write_team_report(req: TeamReportRequest) -> str:
    """Stitch the team members' reports into one."""
    parts = ["# Team report\n"]
    for i, m in enumerate(req.members, 1):
        parts.append(f"\n---\n\n## {i}. {m.question}\n\n**Answer:** {m.summary}\n")
        if m.report_path and Path(m.report_path).exists():
            body = Path(m.report_path).read_text()
            # Demote headings so each member's report nests under its question.
            parts.append("\n" + "\n".join("##" + line if line.startswith("#") else line for line in body.splitlines()) + "\n")
    for q in req.failed:
        parts.append(f"\n---\n\n## ✗ {q}\n\nThis analyst didn't finish.\n")
    Path(req.path).parent.mkdir(parents=True, exist_ok=True)
    Path(req.path).write_text("".join(parts))
    return req.path


AGENT_ACTIVITIES = [publish_report, write_team_report]
