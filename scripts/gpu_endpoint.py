"""A shared model endpoint for a cohort: one Daytona RTX 4090 running vLLM.

Every learner's Max calls it instead of Ollama on their own VM's CPU (see
instruqt/README.md). GPU sandboxes are deleted when they stop, so start one
before a session and let the lifetime end it:

    uv run python scripts/gpu_endpoint.py up [--hours 2]   # prints the config.yml values
    uv run python scripts/gpu_endpoint.py status
    uv run python scripts/gpu_endpoint.py down

Needs DAYTONA_API_KEY for an org with GPU quota (free credits don't cover GPUs).
The first `up` on an org builds the vLLM snapshot, which takes about 45 minutes
and no GPU time. After that, `up` takes about 5 minutes: 4 s for the sandbox, the
rest downloading and loading the model.

Measured on 2026-10-06 (Qwen3.5-9B FP8 + MTP, Max's real requests): median 4.8 s
per call for one learner, 9.1 s with 10 at once, 12.4 s with 30 at once.
"""

import argparse
import sys
import time

from daytona import (
    CreateSandboxFromSnapshotParams,
    CreateSnapshotParams,
    Daytona,
    DaytonaNotFoundError,
    GpuType,
    Resources,
    SessionExecuteRequest,
)

IMAGE = "vllm/vllm-openai:v0.31.0-cu129"
SNAPSHOT = "gpubench-vllm-0310-cu129"
LABEL = {"app": "max-llm"}
MODEL, SERVED_AS = "Qwen/Qwen3.5-9B", "qwen3.5-9b"
VLLM = (
    f"vllm serve {MODEL} --served-model-name {SERVED_AS} --port 8000 --language-model-only "
    "--quantization fp8_per_tensor "
    # Max's prompt reaches ~14k tokens by step 8, plus 2048 for the reply: 16k overflowed.
    "--max-model-len 32768 --max-num-seqs 32 "
    "--enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 "
    "--default-chat-template-kwargs '{\"enable_thinking\": false}' "
    '--speculative-config \'{"method":"qwen3_next_mtp","num_speculative_tokens":2}\''
)

d = Daytona()


def find():
    return next((sb for sb in d.list() if (sb.labels or {}).get("app") == LABEL["app"]), None)


def ensure_snapshot() -> None:
    try:
        if "ACTIVE" in str(d.snapshot.get(SNAPSHOT).state):
            return
    except DaytonaNotFoundError:
        pass
    print(f"building snapshot {SNAPSHOT} from {IMAGE} (about 45 min, no GPU time)...")
    d.snapshot.create(
        # The image's entrypoint is `vllm serve`; a sandbox needs a long-running process instead.
        CreateSnapshotParams(
            name=SNAPSHOT,
            image=IMAGE,
            resources=Resources(cpu=4, memory=16, disk=60, gpu=1, gpu_type=GpuType.RTX_4090),
            entrypoint=["sleep", "infinity"],
        ),
        timeout=0,
    )


def up(hours: float) -> None:
    if find():
        sys.exit("an endpoint is already running: `status` to see it, `down` to remove it")
    ensure_snapshot()
    minutes = int(hours * 60)
    try:
        sb = d.create(
            CreateSandboxFromSnapshotParams(
                snapshot=SNAPSHOT,
                labels=LABEL,
                auto_stop_interval=0,  # learners' traffic is bursty; don't idle-stop mid-session...
                auto_delete_interval=0,
                ttl_minutes=minutes,  # ...the wall-clock lifetime is the cost guard
            ),
            timeout=900,
        )
    except BaseException:
        if leftover := find():
            leftover.delete()
        raise
    print(f"sandbox {sb.id} up; deleted automatically in {minutes} min")
    # The CUDA 12.9 image ships a torchcodec built for CUDA 13, which crashes vLLM at
    # import. Max sends no audio, so remove it.
    sb.process.exec("pip uninstall -y torchcodec >/dev/null 2>&1 || true", timeout=120)
    sb.process.create_session("vllm")
    sb.process.execute_session_command(
        "vllm", SessionExecuteRequest(command=f"nohup {VLLM} > /tmp/vllm.log 2>&1 &", run_async=True)
    )
    t = time.monotonic()
    while time.monotonic() - t < 1200:
        time.sleep(15)
        probe = sb.process.exec(
            "curl -s -o /dev/null -w '%{http_code}' localhost:8000/v1/models;"
            " pgrep -f 'vllm serve' >/dev/null || echo ' dead'",
            timeout=30,
        ).result
        if "dead" in probe:
            print(sb.process.exec("tail -n 30 /tmp/vllm.log").result)
            sb.delete()
            sys.exit("vLLM crashed; the sandbox is deleted")
        if probe.startswith("200"):
            break
    else:
        sb.delete()
        sys.exit("vLLM wasn't ready after 20 min; the sandbox is deleted")
    print(f"vLLM ready after {time.monotonic() - t:.0f}s")
    # The token is in the hostname, so the URL is the credential: one port, revocable,
    # and valid for the sandbox's lifetime (24 h at most).
    url = sb.create_signed_preview_url(8000, expires_in_seconds=min(minutes * 60, 86400)).url
    print("\nPut these in instruqt/sandbox/config.yml, push and publish, and don't commit them:\n")
    print(f'      LLM_MODEL: {SERVED_AS}\n      LLM_BASE_URL: "{url}/v1"\n      LLM_API_KEY: "unused"')


def status() -> None:
    sb = find()
    if not sb:
        print("no endpoint running")
        return
    print(f"{sb.id} {sb.state}")
    print(sb.process.exec("curl -s localhost:8000/v1/models | head -c 200; echo", timeout=30).result)


def down() -> None:
    sb = find()
    if not sb:
        print("no endpoint running")
        return
    sb.delete()
    print(f"deleted {sb.id}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["up", "status", "down"])
    p.add_argument("--hours", type=float, default=2, help="lifetime before Daytona deletes it")
    args = p.parse_args()
    {"up": lambda: up(args.hours), "status": status, "down": down}[args.command]()


if __name__ == "__main__":
    main()
