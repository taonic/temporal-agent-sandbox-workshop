"""Challenge 1: Max can act. Its tool calls reach the sandbox and the run finishes."""

from max_agent.agent.workflow import MaxWorkflow
from max_agent.client import analysis_input, new_id


async def test_max_runs_code_in_its_sandbox_and_finishes(worker, settings):
    inp = analysis_input("Which store sells the most?", settings).model_copy(update={"interactive": False})
    handle = await worker.start_workflow(MaxWorkflow.run, inp, id=new_id("check", settings), task_queue=settings.task_queue)
    try:
        result = await _result(handle)
    except TimeoutError:
        raise AssertionError(
            "Max didn't finish within 30s. Open the workflow in the Temporal UI: a failing "
            "workflow task usually means _handle_tool_call still raises NotImplementedError."
        )
    assert "Top store" in result.summary, "finish should store the model's summary in self._finish_summary"
    assert result.report_path and result.chart_path, "run_python should run the model's code in the sandbox"
    kinds = [s.kind for s in (await handle.query(MaxWorkflow.status)).steps]
    assert "run_python" in kinds and "finish" in kinds


async def _result(handle):
    import asyncio

    return await asyncio.wait_for(handle.result(), timeout=30)
