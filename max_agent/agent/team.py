"""TeamWorkflow: several Maxes at once, one question (and one sandbox) each.

Each team member is a child MaxWorkflow, so it has its own history, its own
sandbox and its own place in the Temporal UI. Cancel the team and the
cancellation flows down: team -> each Max -> each sandbox -> deleted.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from max_agent.agent.activities import TeamReportRequest, write_team_report
    from max_agent.agent.models import AnalysisResult, TeamInput, TeamResult
    from max_agent.agent.workflow import MaxWorkflow


@workflow.defn
class TeamWorkflow:
    @workflow.init
    def __init__(self, inp: TeamInput) -> None:
        self._member_ids = [f"{workflow.info().workflow_id}-q{i + 1}" for i in range(len(inp.questions))]

    @workflow.run
    async def run(self, inp: TeamInput) -> TeamResult:
        members = [inp.base.model_copy(update={"question": q, "interactive": False}) for q in inp.questions]

        # Start every member first, then wait for all of them: they run side by side.
        handles = [
            await workflow.start_child_workflow(MaxWorkflow.run, member, id=member_id, static_summary=member.question)
            for member, member_id in zip(members, self._member_ids)
        ]
        # return_exceptions: one analyst failing shouldn't sink the whole team.
        outcomes = await asyncio.gather(*handles, return_exceptions=True)

        done: list[AnalysisResult] = []
        failed: list[str] = []
        for question, outcome in zip(inp.questions, outcomes):
            if isinstance(outcome, BaseException):
                if isinstance(outcome, asyncio.CancelledError):
                    raise outcome
                workflow.logger.warning("team member failed: %s", outcome)
                failed.append(question)
            else:
                done.append(AnalysisResult.model_validate(outcome))

        path = await workflow.execute_activity(
            write_team_report,
            TeamReportRequest(
                path=f"{inp.base.artifacts_dir}/{workflow.info().workflow_id}/report.md", members=done, failed=failed
            ),
            start_to_close_timeout=timedelta(seconds=30),
        )
        return TeamResult(report_path=path, members=done, failed=failed)

    @workflow.query
    def member_ids(self) -> list[str]:
        return self._member_ids
