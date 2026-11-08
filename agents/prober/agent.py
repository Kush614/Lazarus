"""lazarus-prober: Muse Code writes probes, the port, and regression tests."""
import asyncio
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

from dotenv import load_dotenv
from fetch_hackkit import HackAgent

from agents.prober.muse_client import MuseError, read_json_output, run_exec
from core.schemas import Probe, Request
from core.trust import is_command, is_peer

ROOT = pathlib.Path(__file__).parent.parent.parent
HERE = pathlib.Path(__file__).parent
PORT = ROOT / "port"
load_dotenv(ROOT / ".env")

agent = HackAgent("LAZARUS Prober", seed=os.environ["AGENT_SEED_PHRASE_PROBER"], port=8002, handle="lazarus-prober",
                  description="Writes probes and behavioral ports for software archaeology; used by @lazarus-digger.",
                  readme_path=str(HERE / "README.md"))


def prompt(name: str, **fields) -> str:
    text = (HERE / "prompts" / f"{name}.md").read_text()
    return text + "\n\n" + "\n\n".join(f"{k.upper()}:\n{v}" for k, v in fields.items())


def design_probes(cmd):
    _, ws = run_exec("probe_design", prompt("design_probes", hypothesis=json.dumps(cmd["hypothesis"]), strategy=cmd["strategy"]))
    try:
        data = read_json_output(ws)
        h = cmd["hypothesis"]["id"]
        return {"probes": [Probe(**{**p, "id": "P-new", "hypothesis_id": h}).model_dump() for p in data["probes"]][:3]}
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def _sync_port(ws):
    """Copies generated code back. A new port replaces the old one entirely."""
    if not (ws / "app.py").exists():
        raise MuseError("Muse Code did not produce app.py")
    for child in PORT.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(ws, PORT, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", ".muse", ".git", "output.json"))


def write_port(cmd):
    _, ws = run_exec("port_generation", prompt("write_port", observed=json.dumps(cmd["observed"]), inferred=json.dumps(cmd["inferred"]), traces=json.dumps(cmd["traces"])))
    try:
        _sync_port(ws)
        return {"ok": True}
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def patch_port(cmd):
    _, ws = run_exec("port_patch", prompt("patch_port", observed=json.dumps(cmd["observed"]), divergence=json.dumps(cmd["divergence"])), seed_dir=PORT)
    try:
        _sync_port(ws)
        return {"ok": True}
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def concretize(cmd):
    _, ws = run_exec("concretize", prompt("concretize", description=cmd["description"]))
    try:
        return {"request": Request(**read_json_output(ws)["request"]).model_dump()}
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def apply_strategy_diff(cmd):
    """`patch` applies the model's diff, so a malformed diff fails loudly instead of corrupting the playbook."""
    with tempfile.TemporaryDirectory() as td:
        f = pathlib.Path(td) / "strategy.md"
        f.write_text(cmd["strategy"])
        p = subprocess.run(["patch", "--batch", str(f)], input=cmd["diff"], text=True, capture_output=True)
        if p.returncode:
            raise MuseError(f"strategy diff did not apply: {p.stdout[-200:]}")
        return {"strategy": f.read_text()}


def restore_port(cmd):
    """Drops a port the sentinel blocked, back to the last committed one."""
    subprocess.run(["git", "restore", "--staged", "--worktree", "--", "port"], cwd=ROOT, check=True, capture_output=True)
    subprocess.run(["git", "clean", "-fdq", "--", "port"], cwd=ROOT, check=True, capture_output=True)
    return {"ok": True}


HANDLERS = {"restore_port": restore_port, "design_probes": design_probes, "write_port": write_port, "patch_port": patch_port,
            "concretize": concretize, "apply_strategy_diff": apply_strategy_diff}


@agent.on_text
async def on_text(ctx, msg):
    if not is_command(msg.text):
        return "I work for @lazarus-digger. Say `Exhume` to it."
    if not is_peer(msg.sender):
        return "Internal commands are only accepted from LAZARUS agents."
    cmd = json.loads(msg.text)
    try:
        return json.dumps(await asyncio.to_thread(HANDLERS[cmd["cmd"]], cmd))
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    agent.run()
