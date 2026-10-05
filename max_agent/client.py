"""Client helpers shared by the web app, the CLI and the checks."""

import secrets

from temporalio.client import Client, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter

from max_agent.agent.models import AnalysisInput, LLMSettings, TeamInput
from max_agent.config import Settings, settings
from max_agent.datasets import tables, working_copy
from max_agent.sandbox.models import ProviderConfig


async def connect(s: Settings = settings) -> Client:
    return await Client.connect(s.temporal_address, namespace=s.temporal_namespace, data_converter=pydantic_data_converter)


def provider_config(s: Settings = settings) -> ProviderConfig:
    if s.sandbox_provider == "daytona":
        return ProviderConfig(type="daytona", options={"snapshot": s.daytona_snapshot})
    return ProviderConfig(type=s.sandbox_provider)


def analysis_input(question: str, s: Settings = settings) -> AnalysisInput:
    # Settings are captured here, once, into the workflow input. The workflow
    # never reads the environment, so replays always see the same values.
    return AnalysisInput(
        question=question,
        data_dir=str(working_copy(s).resolve()),
        tables=tables(s),
        artifacts_dir=str(s.artifacts_dir.resolve()),
        llm=LLMSettings(mode=s.llm_mode, model=s.llm_model),
        provider=provider_config(s),
        learner_id=s.learner_id,
        idle_timeout_s=s.idle_timeout_s,
        approval_timeout_s=s.approval_timeout_s,
        max_steps=s.max_steps,
    )


def new_id(kind: str, s: Settings = settings) -> str:
    # Also used as the sandbox name, so keep it short, lowercase and unique per org.
    return f"{kind}-{s.learner_id}-{secrets.token_hex(3)}".lower()


async def start_max(client: Client, question: str, s: Settings = settings) -> WorkflowHandle:
    from max_agent.agent.workflow import MaxWorkflow

    return await client.start_workflow(
        MaxWorkflow.run, analysis_input(question, s), id=new_id("max", s), task_queue=s.task_queue, static_summary=question
    )


async def start_team(client: Client, questions: list[str], s: Settings = settings) -> WorkflowHandle:
    from max_agent.agent.team import TeamWorkflow

    questions = questions[: s.max_parallel]
    return await client.start_workflow(
        TeamWorkflow.run,
        TeamInput(questions=questions, base=analysis_input(questions[0], s)),
        id=new_id("team", s),
        task_queue=s.task_queue,
        static_summary=f"{len(questions)} questions",
    )
