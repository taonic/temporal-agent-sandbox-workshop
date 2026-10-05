"""MaxWorkflow: Max, a personal analyst agent with its own computer.

The reasoning (the agent loop) runs here, in the workflow. The work (running
code) happens in a sandbox. Every model call and every sandbox call is a
step in this workflow's history, so Max survives crashes, restarts and
deploys without losing its place, repeating work or leaking sandboxes.

Lifecycle of one Max:
  create sandbox -> upload data -> agent loop -> fetch report
  -> ask to publish -> wait for new data (sandbox sleeps) -> rerun ... -> retire
"""

import asyncio
import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError, FailureError

with workflow.unsafe.imports_passed_through():
    from max_agent.agent.activities import PublishRequest, publish_report
    from max_agent.agent.llm import call_llm
    from max_agent.agent.models import (
        AnalysisInput,
        AnalysisResult,
        Decision,
        LLMRequest,
        LLMResponse,
        Phase,
        RunStatus,
        Step,
        ToolCall,
    )
    from max_agent.agent.prompts import PREAMBLE, SYSTEM_PROMPT, TOOLS
    from max_agent.sandbox.handle import Sandbox
    from max_agent.sandbox.models import FileTransfer, SandboxSpec

MAX_OUTPUT_CHARS = 3000


@workflow.defn
class MaxWorkflow:
    @workflow.init
    def __init__(self, inp: AnalysisInput) -> None:
        self._inp = inp
        self._phase = Phase.STARTING
        self._steps: list[Step] = []
        self._sandbox: Sandbox | None = None
        self._result: AnalysisResult | None = None
        self._finish_summary: str | None = None
        self._published = False
        self._reruns = 0
        self._new_data = False
        self._dismissed = False
        self._decision: Decision | None = None
        self._approval_deadline: str | None = None

    @workflow.run
    async def run(self, inp: AnalysisInput) -> AnalysisResult:
        wf_id = workflow.info().workflow_id
        self._sandbox = await Sandbox.create(
            inp.provider,
            SandboxSpec(name=wf_id, labels={"app": "max", "learner": inp.learner_id, "workflow": wf_id}),
            idle_timeout_s=inp.idle_timeout_s,
        )
        self._note(f"Got a computer ({inp.provider.type} sandbox)")
        try:
            while True:
                await self._sandbox.upload(
                    [FileTransfer(remote_path=f"data/{t}.csv", local_path=f"{inp.data_dir}/{t}.csv") for t in inp.tables]
                )
                self._result = await self._analyze()
                if not inp.interactive:
                    break

                await self._ask_to_publish()

                # Nothing to do until new data shows up. Max just waits here: no
                # polling, no cost. Meanwhile the sandbox notices it's idle and
                # suspends itself; the next upload will wake it up again.
                self._phase = Phase.WAITING_FOR_DATA
                try:
                    await workflow.wait_condition(
                        lambda: self._new_data or self._dismissed, timeout=timedelta(seconds=inp.linger_timeout_s)
                    )
                except asyncio.TimeoutError:
                    self._note("No new data for a while; retiring")
                if not self._new_data:
                    break
                self._new_data = False
                self._reruns += 1
                self._note("New data arrived; rerunning the analysis")
        except (asyncio.CancelledError, FailureError):
            # Max is really ending (cancelled, or failed for good): delete its computer.
            self._note("Stopping")
            await self._sandbox.stop()
            raise
        # Any other exception is a bug in this code. Temporal doesn't end the run for
        # that: it pauses it (the workflow task is retried) until you deploy a fix.
        # So we must NOT clean up on bugs, or the run couldn't resume with its sandbox.

        await self._sandbox.stop()
        self._phase = Phase.DONE
        return self._result

    # ------------------------------------------------------------- agent loop

    async def _analyze(self) -> AnalysisResult:
        self._phase = Phase.ANALYZING
        self._finish_summary = None
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._inp.question},
        ]
        nudged = False
        steps_used = 0
        for steps_used in range(1, self._inp.max_steps + 1):
            response: LLMResponse = await workflow.execute_activity(
                call_llm,
                LLMRequest(settings=self._inp.llm, messages=messages, tools=TOOLS),
                start_to_close_timeout=timedelta(minutes=10),  # small models on CPUs are slow
                heartbeat_timeout=timedelta(seconds=30),  # ...but a dead worker is noticed fast
                # No attempt limit: if the model server is down, Max waits for it
                # (retrying with backoff) instead of failing. Errors that retrying
                # can't fix (bad request, bad key) are raised as non-retryable.
                retry_policy=RetryPolicy(maximum_interval=timedelta(seconds=30)),
                summary=f"think (step {steps_used})",
            )
            messages.append(_assistant_message(response))
            if response.content:
                self._add_step("think", response.content[:200], response.content)

            if not response.tool_calls:
                if nudged:
                    self._finish_summary = response.content or "No answer."
                    break
                nudged = True
                messages.append(
                    {"role": "user", "content": "Use your tools: save out/report.md and out/chart.png, then call finish."}
                )
                continue

            for call in response.tool_calls:
                output = await self._handle_tool_call(call)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
            if self._finish_summary is not None:
                break
        else:
            self._note(f"Out of steps ({self._inp.max_steps}); wrapping up with what I have")

        return await self._collect_result(self._finish_summary or "I ran out of steps before finishing.", steps_used)

    async def _handle_tool_call(self, call: ToolCall) -> str:
        """Carry out one tool call from the model. Returns what to tell the model."""
        if call.name == "run_python":
            return await self._run_python(call.arguments.get("code", ""))
        if call.name == "finish":
            self._finish_summary = call.arguments.get("summary", "")
            self._add_step("finish", self._finish_summary)
            return "ok"
        self._note(f"Model asked for an unknown tool: {call.name}")
        return f"Unknown tool {call.name!r}. Use run_python or finish."

    async def _run_python(self, code: str) -> str:
        n = len(self._steps) + 1
        path = f"steps/step_{n}.py"
        result = await self._sandbox.exec(f"python3 {path}", files={path: PREAMBLE + code}, timeout_s=90)
        output = _truncate(result.output)
        self._add_step("run_python", f"ran {path} → exit {result.exit_code}", f"{code}\n\n--- output ---\n{output}")
        return f"exit code: {result.exit_code}\n{output}"

    async def _collect_result(self, summary: str, steps_used: int) -> AnalysisResult:
        local = f"{self._inp.artifacts_dir}/{workflow.info().workflow_id}/run{self._reruns}"
        saved = await self._sandbox.download(
            [
                FileTransfer(remote_path="out/report.md", local_path=f"{local}/report.md"),
                FileTransfer(remote_path="out/chart.png", local_path=f"{local}/chart.png"),
            ]
        )
        return AnalysisResult(
            question=self._inp.question,
            summary=summary,
            report_path=next((p for p in saved if p.endswith(".md")), None),
            chart_path=next((p for p in saved if p.endswith(".png")), None),
            steps_used=steps_used,
        )

    # --------------------------------------------------------- human in loop

    async def _ask_to_publish(self) -> None:
        """Max never posts on its own: a human approves first."""
        self._decision = None
        self._phase = Phase.AWAITING_APPROVAL
        timeout = timedelta(seconds=self._inp.approval_timeout_s)
        self._approval_deadline = (workflow.now() + timeout).isoformat(timespec="seconds")
        try:
            # Wait for a person. Could be seconds, could be days: either way it
            # costs nothing and survives restarts.
            await workflow.wait_condition(lambda: self._decision is not None or self._dismissed, timeout=timeout)
        except asyncio.TimeoutError:
            self._note("Nobody approved in time; keeping the report, not posting it")
            return
        finally:
            self._approval_deadline = None

        if self._decision is None:  # dismissed while waiting
            return
        if not self._decision.approve:
            self._note(f"{self._decision.by} said no; not posting")
            return
        self._phase = Phase.PUBLISHING
        await workflow.execute_activity(
            publish_report,
            PublishRequest(
                post_id=f"{workflow.info().workflow_id}/run{self._reruns}",
                workflow_id=workflow.info().workflow_id,
                result=self._result,
                approved_by=self._decision.by,
            ),
            start_to_close_timeout=timedelta(seconds=30),
        )
        self._published = True
        self._note(f"Posted to #analytics (approved by {self._decision.by})")

    @workflow.update
    def approve_publish(self, decision: Decision) -> str:
        self._decision = decision
        return "posting" if decision.approve else "not posting"

    @approve_publish.validator
    def validate_approve_publish(self, decision: Decision) -> None:
        # Validators run before anything is written to history: a late or
        # duplicate click is rejected without leaving a trace.
        if self._phase != Phase.AWAITING_APPROVAL or self._decision is not None:
            raise ApplicationError("Max isn't waiting for approval right now", type="NotAwaitingApproval")

    # ---------------------------------------------------------- other inputs

    @workflow.signal
    def new_data(self) -> None:
        self._new_data = True

    @workflow.signal
    def dismiss(self) -> None:
        self._dismissed = True

    @workflow.query
    def status(self) -> RunStatus:
        return RunStatus(
            question=self._inp.question,
            phase=self._phase,
            steps=self._steps,
            sandbox_workflow_id=self._sandbox.workflow_id if self._sandbox else None,
            result=self._result,
            published=self._published,
            reruns=self._reruns,
            approval_deadline=self._approval_deadline,
        )

    # ---------------------------------------------------------------- helpers

    def _add_step(self, kind: str, summary: str, detail: str = "") -> None:
        self._steps.append(
            Step(n=len(self._steps) + 1, kind=kind, summary=summary, detail=detail, at=workflow.now().isoformat(timespec="seconds"))
        )

    def _note(self, text: str) -> None:
        workflow.logger.info(text)
        self._add_step("note", text)


def _assistant_message(r: LLMResponse) -> dict:
    msg: dict = {"role": "assistant", "content": r.content or ""}
    if r.tool_calls:
        msg["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in r.tool_calls
        ]
    return msg


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    # Keep the start (context) and the end (where errors are).
    return text[:1000] + "\n... (output truncated) ...\n" + text[-(MAX_OUTPUT_CHARS - 1000):]
