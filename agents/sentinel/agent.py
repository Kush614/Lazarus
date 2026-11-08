"""lazarus-sentinel: blocks unsafe generated code before it can run. Deterministic, no LLM."""
import json
import os
import pathlib

from dotenv import load_dotenv
from fetch_hackkit import HackAgent, cards

from agents.sentinel.scan import Finding, Verdict, scan_port, scan_source
from core.trust import is_command, is_peer

ROOT = pathlib.Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")

agent = HackAgent(
    "LAZARUS Sentinel", seed=os.environ["AGENT_SEED_PHRASE_SENTINEL"], port=8004, handle="lazarus-sentinel",
    description="Release control for AI-generated Python: a static review that blocks code which runs other programs, "
                "calls the network, reads secrets or hunts for test answers. It never executes what it reviews. Paste code to scan it.",
    readme_path=str(ROOT / "agents/sentinel/README.md"))


def form():
    return cards.form("Review AI-generated code", [cards.field("code", "Python to review", "textarea", required=True, placeholder="Paste the code. It is parsed, never run.")],
                      submit=cards.cta("Review it", "scan_code", primary=True), narration="I block code that should not be run, before anyone runs it.")


def verdict_card(findings: list[Finding], files: int = 1):
    if not findings:
        return cards.info("Passed", rows={"Files reviewed": files, "Findings": "none"}, narration="Nothing here should stop it from running. This is a static review, not proof that it behaves correctly.")
    rows = {f"{f.file}:{f.line} {f.rule}": f.why for f in findings[:12]}
    if len(findings) > 12:
        rows["More"] = f"{len(findings) - 12} further findings"
    return cards.detail("Blocked", rows=rows, ctas=[cards.cta("Review something else", "show_form")], narration=f"{len(findings)} finding(s). This should not be run as it stands.")


def _internal(cmd: dict) -> dict:
    if cmd["cmd"] == "review":
        return scan_port(ROOT / "port").model_dump()
    raise ValueError(f"unknown cmd {cmd['cmd']}")


@agent.on_action("show_form")
async def _form(ctx, msg, sel):
    return form()


@agent.on_action("scan_code")
async def _scan(ctx, msg, sel):
    code = sel.get("code") or ""
    return verdict_card(scan_source(code)) if code.strip() else form()


@agent.on_text
async def on_text(ctx, msg):
    text = msg.text.strip()
    if is_command(text):
        if not is_peer(msg.sender):
            return "Internal commands are only accepted from LAZARUS agents."
        try:
            return json.dumps(_internal(json.loads(text)))
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})
    if "\n" in text or text.startswith(("import ", "from ", "def ", "class ")):
        return verdict_card(scan_source(text.removeprefix("```python").removeprefix("```").removesuffix("```")))
    return form()


__all__ = ["Verdict", "agent"]

if __name__ == "__main__":
    agent.run()
