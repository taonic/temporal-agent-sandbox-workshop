"""The one activity that talks to the model.

Every model call is an activity, so Temporal records each response in history.
If the worker dies mid-run, finished calls are never repeated (and never re-billed);
the run picks up exactly where it stopped.
"""

import asyncio
import json
from contextlib import asynccontextmanager

import openai
from openai import AsyncOpenAI
from temporalio import activity
from temporalio.exceptions import ApplicationError

from max_agent.agent.models import LLMRequest, LLMResponse, ToolCall
from max_agent.agent.scripted import scripted_response
from max_agent.config import settings


@asynccontextmanager
async def heartbeating(every_s: float = 5.0):
    """Heartbeat while a slow call runs, so a dead worker is noticed in seconds
    (heartbeat_timeout) instead of minutes (start_to_close_timeout)."""

    async def beat():
        while True:
            activity.heartbeat()
            await asyncio.sleep(every_s)

    task = asyncio.create_task(beat())
    try:
        yield
    finally:
        task.cancel()


def _parse_args(raw: str | None) -> dict:
    try:
        args = json.loads(raw or "{}")
        return args if isinstance(args, dict) else {"_raw": raw}
    except json.JSONDecodeError:
        return {"_raw": raw}  # small models sometimes emit broken JSON; let the workflow say so


@activity.defn
async def call_llm(req: LLMRequest) -> LLMResponse:
    if req.settings.mode == "scripted":
        return scripted_response(req)

    client = AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        max_retries=0,  # Temporal owns retries
        timeout=600,
    )
    try:
        async with heartbeating():
            resp = await client.chat.completions.create(
                model=req.settings.model,
                messages=req.messages,
                tools=req.tools,
                # One tool offered (finish, on Max's last step) means it must be called: left to
                # "auto", small models even call tools they weren't given.
                tool_choice="required" if len(req.tools) == 1 else "auto",
                temperature=0.2,
                max_tokens=2048,  # a runaway reply would block single-slot servers like Ollama
                reasoning_effort="none",  # Qwen's thinking mode: slow on CPU, not needed here
            )
    except (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError, openai.BadRequestError) as e:
        raise ApplicationError(f"LLM request rejected: {e}", type=type(e).__name__, non_retryable=True) from e

    msg = resp.choices[0].message
    return LLMResponse(
        content=msg.content,
        tool_calls=[
            ToolCall(id=tc.id or f"call_{i}", name=tc.function.name, arguments=_parse_args(tc.function.arguments))
            for i, tc in enumerate(msg.tool_calls or [])
        ],
        usage=resp.usage.model_dump() if resp.usage else {},
    )
