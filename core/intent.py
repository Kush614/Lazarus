"""Turns a user's words into an action. ASI:One's planner rewrites messages as prose before
they reach an agent, so matching the start of the text is not enough.

Rules run first because they are free, fast and work with no key. ASI:One's model is only
asked about what the rules miss, and any failure there falls back to the help card."""
import re
from typing import Literal

from pydantic import BaseModel

Name = Literal["exhume", "show_dig", "resurrect", "hunt", "reveal", "status", "use_cases", "report", "scout", "review", "challenge", "receipt", "help"]

RULES: list[tuple[Name, str]] = [
    ("show_dig", r"show (me )?the dig|ledger|\bclaims?\b|hypothes"),
    ("reveal", r"\breveal\b|break the seal|show (me )?the source"),
    ("exhume", r"\bexhume\b|(start|begin|run) (a |the )?dig|reverse.?engineer|dig (it )?up"),
    ("resurrect", r"\bresurrect\b|write the port|port it\b|rewrite it"),
    ("challenge", r"\bchallenge\b|try to break|free (try|test)|test it myself"),
    ("receipt", r"\breceipt\b|\bverify\b|\bproof\b|check (the )?seal"),
    ("hunt", r"\bhunt\b|\bbounty\b|\bstake\b|prove .*wrong"),
    ("scout", r"\bscout\b|\bfuzz|differential"),
    ("review", r"\bsentinel\b|safety (review|scan|check)|security (review|scan|check)"),
    ("report", r"\breport\b|\bevidence\b|\bspec\b|documentation"),
    ("use_cases", r"use.?cases?|who is (this|it) for|what else|what can (you|it|this) (do|be used)"),
    ("status", r"\bstatus\b|progress|where are we|how far|current score"),
]


class Intent(BaseModel):
    intent: Name


def by_rules(text: str) -> Name | None:
    low = text.lower()
    for name, pattern in RULES:
        if re.search(pattern, low):
            return name
    return None


async def route(text: str, llm=None) -> Name:
    """`llm` is an ASI1 client, or None to run on rules alone."""
    hit = by_rules(text)
    if hit or llm is None or not text.strip():
        return hit or "help"
    try:
        return (await llm.structured(text, Intent, system=(
            "Classify what the user wants from LAZARUS, a system that reverse engineers a binary with no source. "
            "exhume: start digging. show_dig: see the claims. resurrect: write the port. hunt: try to break the port for a bounty. "
            "reveal: decrypt the sealed source. status: where things stand. use_cases: what it could be used for. "
            "report: the evidence document. scout: test the port for differences. review: a safety scan of the code. "
            "challenge: a free try at breaking the port. receipt: a checkable proof of the run. help: anything else."))).intent
    except Exception:
        return "help"
