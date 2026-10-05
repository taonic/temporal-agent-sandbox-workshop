"""A scripted stand-in for the LLM.

Same activity, same message format, no model. Used by challenge checks and as
a fallback if the real model misbehaves during a live session. It always plays
the same two moves: run one analysis script, then finish with what it printed.
"""

from max_agent.agent.models import LLMRequest, LLMResponse, ToolCall

ANALYSIS_SCRIPT = '''\
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

df = pd.read_csv("data/sales.csv", parse_dates=["date"])
by_store = df.groupby("store")["revenue"].sum().sort_values(ascending=False)
by_drink = df.groupby("drink")["revenue"].sum().sort_values(ascending=False)
days = df["date"].nunique()
last = df["date"].max().date()

os.makedirs("out", exist_ok=True)
ax = by_store.plot(kind="bar", color="#4f6bed", title="Revenue by store")
ax.set_ylabel("USD")
plt.tight_layout()
plt.savefig("out/chart.png", dpi=120)

with open("out/report.md", "w") as f:
    f.write(f"# Coffee sales: {days} days through {last}\\n\\n")
    f.write("_Scripted mode: a fixed analysis, no model involved._\\n\\n")
    f.write("## Revenue by store\\n\\n")
    for store, rev in by_store.items():
        f.write(f"- **{store}**: ${rev:,.0f}\\n")
    f.write("\\n## Top drinks\\n\\n")
    for drink, rev in by_drink.head(3).items():
        f.write(f"- {drink}: ${rev:,.0f}\\n")

print(f"Top store: {by_store.index[0]} (${by_store.iloc[0]:,.0f}) over {days} days through {last}.")
print(f"Top drink: {by_drink.index[0]}.")
'''


def scripted_response(req: LLMRequest) -> LLMResponse:
    turn = sum(1 for m in req.messages if m["role"] == "assistant")
    if turn == 0:
        return LLMResponse(tool_calls=[ToolCall(id="call_1", name="run_python", arguments={"code": ANALYSIS_SCRIPT})])
    last_tool = next((m["content"] for m in reversed(req.messages) if m["role"] == "tool"), "")
    lines = [line for line in last_tool.splitlines() if line.startswith("Top ")]
    summary = " ".join(lines) or "Analysis complete; see the report."
    return LLMResponse(tool_calls=[ToolCall(id=f"call_{turn + 1}", name="finish", arguments={"summary": summary})])
