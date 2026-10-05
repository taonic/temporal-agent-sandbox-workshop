from enum import Enum

from pydantic import BaseModel, Field

from max_agent.sandbox.models import ProviderConfig


class LLMSettings(BaseModel):
    # The input says *what* to use. *Where* it lives (endpoint URL, API key) is
    # the worker's business: it reads LLM_BASE_URL / LLM_API_KEY from its own
    # environment, so secrets never land in workflow history.
    mode: str = "openai"  # "openai" (any OpenAI-compatible endpoint) | "scripted"
    model: str = "qwen3.5:4b"


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict


class LLMRequest(BaseModel):
    settings: LLMSettings
    messages: list[dict]
    tools: list[dict]


class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)


class AnalysisInput(BaseModel):
    question: str
    data_dir: str  # local working copy of the dataset; each table is uploaded as data/<table>.csv
    tables: list[str]
    artifacts_dir: str  # where reports and charts land on this machine
    llm: LLMSettings
    provider: ProviderConfig
    learner_id: str = "local"
    idle_timeout_s: int = 60
    approval_timeout_s: int = 180
    linger_timeout_s: int = 1800  # how long Max waits for new data before retiring
    max_steps: int = 8
    # Interactive Max asks before publishing and reruns on new data.
    # Team members (challenge 4) just answer and return.
    interactive: bool = True


class Phase(str, Enum):
    STARTING = "starting"
    ANALYZING = "analyzing"
    AWAITING_APPROVAL = "awaiting_approval"
    PUBLISHING = "publishing"
    WAITING_FOR_DATA = "waiting_for_data"
    DONE = "done"
    FAILED = "failed"


class Step(BaseModel):
    n: int
    kind: str  # "think" | "run_python" | "finish" | "note"
    summary: str
    detail: str = ""
    at: str = ""


class Decision(BaseModel):
    approve: bool
    by: str = "you"


class AnalysisResult(BaseModel):
    question: str
    summary: str
    report_path: str | None = None
    chart_path: str | None = None
    steps_used: int = 0


class RunStatus(BaseModel):
    """What the `status` query returns: everything the web app shows."""

    question: str
    phase: Phase
    steps: list[Step]
    sandbox_workflow_id: str | None = None
    result: AnalysisResult | None = None
    published: bool = False
    reruns: int = 0
    approval_deadline: str | None = None


class TeamInput(BaseModel):
    questions: list[str]
    base: AnalysisInput  # template; each member gets one question


class TeamResult(BaseModel):
    report_path: str
    members: list[AnalysisResult]
    failed: list[str] = Field(default_factory=list)
