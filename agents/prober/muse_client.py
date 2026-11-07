"""Runs Muse Code in a throwaway workspace.

Muse's sandbox only limits WRITES; the rest of the disk stays readable. So each run is
isolated by working directory and its JSON event stream is audited: any mention of a
sealed path fails the run and the output is discarded.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).parent.parent.parent
LOG_DIR = ROOT / "logs" / "meta"
SEALED = re.compile(r"lazarus-sealed|source\.tar|set\.jsonl|AGE_KEY|/lazarus/\.env|AGENT_SEED|relic-darwin|relic-src|\.claude/|\.claude-mem")
TIMEOUT_S = 600


class MuseError(RuntimeError):
    pass


class SealBreach(MuseError):
    pass


def audit(stream: str) -> None:
    """Scans everything Muse did, whatever the event shape."""
    m = SEALED.search(stream)
    if m:
        raise SealBreach(f"Muse Code touched a sealed path ({m.group(0)}); output discarded")


def run_exec(call: str, prompt: str, seed_dir: pathlib.Path | None = None, runner=None) -> tuple[str, pathlib.Path]:
    """Returns (final event stream, workspace). The caller copies files out and removes the workspace."""
    ws = pathlib.Path(tempfile.mkdtemp(prefix="lazarus-muse-"))
    if seed_dir and seed_dir.exists():
        shutil.copytree(seed_dir, ws, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    prompt_file = ws.parent / (ws.name + ".prompt")
    prompt_file.write_text(prompt)
    argv = ["muse", "exec", "--json", "--workspace", str(ws), "--prompt-file", str(prompt_file)]
    env = {k: os.environ[k] for k in ("PATH", "HOME", "META_API_KEY") if k in os.environ}  # never the seeds or age keys
    run = runner or (lambda: subprocess.run(argv, cwd=ws, env=env, capture_output=True, text=True, timeout=TIMEOUT_S))
    last = None
    for _ in range(3):
        try:
            p = run()
        except subprocess.TimeoutExpired:
            last = "timeout"
            continue
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        (LOG_DIR / f"{call}_{time.time_ns()}.json").write_text(json.dumps({"call": call, "prompt": prompt, "stdout": p.stdout, "stderr": p.stderr[-4000:]}))
        audit(p.stdout)
        if p.returncode == 0:
            prompt_file.unlink(missing_ok=True)
            return p.stdout, ws
        last = f"exit {p.returncode}: {p.stderr[-300:]}"
    prompt_file.unlink(missing_ok=True)
    shutil.rmtree(ws, ignore_errors=True)
    raise MuseError(f"{call} failed: {last}")


def read_json_output(ws: pathlib.Path, name: str = "output.json") -> dict:
    p = ws / name
    if not p.exists():
        raise MuseError(f"Muse Code did not write {name}")
    return json.loads(p.read_text())
