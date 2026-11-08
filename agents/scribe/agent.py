"""lazarus-scribe: turns the ledger into a report people can check, and sells the full version."""
import os
import pathlib

from dotenv import load_dotenv
from fetch_hackkit import HackAgent, cards

from agents.scribe.report import Report, build
from core import ledger

ROOT = pathlib.Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")
PRICE_FET = "0.5"

agent = HackAgent(
    "LAZARUS Scribe", seed=os.environ["AGENT_SEED_PHRASE_SCRIBE"], port=8006, handle="lazarus-scribe",
    description="Evidence reports for software reconstruction: every behaviour sorted into observed, inferred or refuted, each linked to the trace behind it, with a hash anyone can check.",
    readme_path=str(ROOT / "agents/scribe/README.md"))
db = ledger.connect()


def summary_card(r: Report):
    return cards.detail("Evidence report", rows={
        "Observed": r.observed, "Inferred": r.inferred, "Refuted": r.refuted, "Port versions": r.versions,
        "Best adopted score": f"{r.best_score:.1%}" if r.best_score is not None else "none yet", "Report hash": r.sha256,
    }, ctas=[cards.cta(f"Get the full report · {PRICE_FET} testnet FET", "full_report", primary=True)],
        narration="Built from records only, with no model writing it. The same records always give the same hash.")


@agent.paid("full_report", amount=PRICE_FET, description="Full LAZARUS evidence report")
async def full_report(ctx, msg, sel):
    r = build(db, ROOT)
    return [r.markdown, f"Report hash: {r.sha256}"]


@agent.on_text
async def on_text(ctx, msg):
    return summary_card(build(db, ROOT))


if __name__ == "__main__":
    agent.run()
