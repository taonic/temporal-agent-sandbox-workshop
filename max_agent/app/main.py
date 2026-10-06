"""Max's web app: ask questions, watch Max work, approve posts, feed it new data.

Everything here is a thin client of Temporal: starting a workflow, sending a
signal or update, and polling queries. The app holds no state of its own:
restart it and nothing is lost.

    uv run uvicorn max_agent.app.main:app --port 8000
"""

import hashlib
import json
from pathlib import Path

import markdown
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowUpdateFailedError
from temporalio.service import RPCError

from max_agent.agent.activities import read_channel
from max_agent.agent.models import Decision
from max_agent.agent.team import TeamWorkflow
from max_agent.agent.workflow import MaxWorkflow
from max_agent.client import connect, start_max, start_team
from max_agent.config import settings
from max_agent.datasets import append_day, day_count
from max_agent.sandbox.workflow import SandboxWorkflow

app = FastAPI(title="Max")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["md"] = lambda text: markdown.markdown(text or "", extensions=["tables", "fenced_code"])
_client: Client | None = None

UI = settings.temporal_ui_url.rstrip("/")


async def client() -> Client:
    global _client
    if _client is None:
        _client = await connect()
    return _client


def ctx(request: Request, **extra) -> dict:
    return {"request": request, "ui": UI, "ns": settings.temporal_namespace, "learner": settings.learner_id, **extra}


# ------------------------------------------------------------------ pages


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    c = await client()
    runs = []
    query = (
        "WorkflowType IN ('MaxWorkflow', 'TeamWorkflow') "
        f"AND (WorkflowId STARTS_WITH 'max-{settings.learner_id}-' OR WorkflowId STARTS_WITH 'team-{settings.learner_id}-')"
    )
    async for wf in c.list_workflows(query, limit=20):
        if wf.workflow_type == "MaxWorkflow" and wf.id.startswith("team-"):
            continue  # team members are shown on their team's page
        runs.append({"id": wf.id, "type": wf.workflow_type, "status": wf.status.name.lower(), "started": wf.start_time})
    return templates.TemplateResponse(
        request, "home.html", ctx(request, runs=runs, days=day_count(), posts=read_channel()[-3:][::-1])
    )


@app.post("/ask")
async def ask(questions: str = Form(...)):
    qs = [q.strip() for q in questions.splitlines() if q.strip()]
    if not qs:
        raise HTTPException(400, "Ask Max something")
    c = await client()
    handle = await (start_max(c, qs[0]) if len(qs) == 1 else start_team(c, qs))
    return RedirectResponse(f"/runs/{handle.id}", status_code=303)


@app.get("/runs/{wf_id}", response_class=HTMLResponse)
async def run_page(request: Request, wf_id: str):
    return templates.TemplateResponse(request, "run.html", ctx(request, wf_id=wf_id))


@app.get("/runs/{wf_id}/panel", response_class=HTMLResponse)
async def run_panel(request: Request, wf_id: str, flash: str = "", v: str = ""):
    """The live part of a run page. The page polls with the version it has;
    if nothing changed we answer 204 and htmx leaves the DOM alone."""
    c = await client()
    handle = c.get_workflow_handle(wf_id)
    try:
        desc = await handle.describe()
    except RPCError:
        raise HTTPException(404, "No such run")
    running = desc.status == WorkflowExecutionStatus.RUNNING

    if desc.workflow_type == "TeamWorkflow":
        members = []
        for member_id in await _safe_query(handle, TeamWorkflow.member_ids) or []:
            members.append({"id": member_id, **await _max_view(c, member_id)})
        report = None
        if desc.status == WorkflowExecutionStatus.COMPLETED:
            result = await handle.result()
            report = Path(result.report_path).read_text() if Path(result.report_path).exists() else None
        version = _version(desc.status, members, report)
        if v and v == version and not flash:
            return Response(status_code=204)
        return templates.TemplateResponse(
            request,
            "team_panel.html",
            ctx(request, wf_id=wf_id, wf_status=desc.status.name.lower(), running=running, members=members,
                report=report, flash=flash, version=version),
        )

    view = await _max_view(c, wf_id)
    version = _version(desc.status, view)
    if v and v == version and not flash:
        return Response(status_code=204)
    return templates.TemplateResponse(
        request,
        "max_panel.html",
        ctx(request, wf_id=wf_id, wf_status=desc.status.name.lower(), running=running, flash=flash, version=version, **view),
    )


def _version(*parts) -> str:
    def plain(x):
        if hasattr(x, "model_dump"):
            return x.model_dump(mode="json")
        if isinstance(x, dict):
            return {k: plain(v) for k, v in x.items()}
        if isinstance(x, list):
            return [plain(i) for i in x]
        return str(x) if x is not None else None

    return hashlib.sha1(json.dumps(plain(list(parts)), sort_keys=True).encode()).hexdigest()[:12]


async def _max_view(c: Client, wf_id: str) -> dict:
    handle = c.get_workflow_handle(wf_id)
    status = await _safe_query(handle, MaxWorkflow.status)
    sandbox = None
    if status and status.sandbox_workflow_id:
        sandbox = await _safe_query(c.get_workflow_handle(status.sandbox_workflow_id), SandboxWorkflow.state)
    report = None
    if status and status.result and status.result.report_path and Path(status.result.report_path).exists():
        report = Path(status.result.report_path).read_text()
    return {"st": status, "sandbox": sandbox, "report": report}


async def _safe_query(handle, query):
    try:
        return await handle.query(query)
    except Exception:
        return None  # not started yet, or no worker to answer: show what we can


# ---------------------------------------------------------------- actions


@app.post("/runs/{wf_id}/approve", response_class=HTMLResponse)
async def approve(request: Request, wf_id: str, approve: str = Form(...)):
    handle = (await client()).get_workflow_handle(wf_id)
    try:
        # By name, not MaxWorkflow.approve_publish: the learner writes that handler in
        # challenge 3, after this app process imported the class without it.
        decision = Decision(approve=approve == "yes", by=settings.learner_id)
        msg = await handle.execute_update("approve_publish", decision, result_type=str)
        flash = f"Max: {msg}"
    except WorkflowUpdateFailedError as e:
        flash = f"Rejected: {e.cause}"  # the workflow's validator said no
    except RPCError as e:
        flash = f"Couldn't deliver: {e.message}"
    except Exception as e:  # noqa: BLE001 -- say so, rather than leave a button that does nothing
        flash = f"Couldn't deliver: {type(e).__name__}: {e}"
    return await run_panel(request, wf_id, flash=flash)


@app.post("/runs/{wf_id}/new-data", response_class=HTMLResponse)
async def new_data(request: Request, wf_id: str):
    day = append_day()
    await (await client()).get_workflow_handle(wf_id).signal(MaxWorkflow.new_data)
    return await run_panel(request, wf_id, flash=f"Dropped in sales for {day}")


@app.post("/runs/{wf_id}/dismiss", response_class=HTMLResponse)
async def dismiss(request: Request, wf_id: str):
    await (await client()).get_workflow_handle(wf_id).signal(MaxWorkflow.dismiss)
    return await run_panel(request, wf_id, flash="Max is retiring; its computer will be deleted")


@app.post("/runs/{wf_id}/cancel", response_class=HTMLResponse)
async def cancel(request: Request, wf_id: str):
    await (await client()).get_workflow_handle(wf_id).cancel()
    return await run_panel(request, wf_id, flash="Cancellation requested")


@app.get("/channel", response_class=HTMLResponse)
async def channel(request: Request):
    return templates.TemplateResponse(request, "channel.html", ctx(request, posts=read_channel()[::-1]))


@app.get("/files")
async def files(path: str):
    target = Path(path).resolve()
    if not target.is_relative_to(settings.artifacts_dir.resolve()) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


def run() -> None:
    import uvicorn

    uvicorn.run("max_agent.app.main:app", host="0.0.0.0", port=int(__import__("os").environ.get("APP_PORT", "8000")))
