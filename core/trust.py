"""Who may send internal commands. Every agent is public on Agentverse, so a `{"cmd": ...}`
message from a stranger must not be able to run probes, write ports or adopt versions."""
import os
from functools import lru_cache

from uagents_core.identity import Identity

ROLES = ("digger", "prober", "oracle", "sentinel", "scout", "scribe")


@lru_cache(maxsize=None)
def _address(seed: str) -> str:
    return Identity.from_seed(seed, 0).address


def address_of(role: str) -> str:
    """Derived from the seed, so peers resolve without waiting on Agentverse handles."""
    return _address(os.environ[f"AGENT_SEED_PHRASE_{role.upper()}"])


def is_peer(sender: str) -> bool:
    for role in ROLES:
        seed = os.environ.get(f"AGENT_SEED_PHRASE_{role.upper()}")
        if seed and _address(seed) == sender:
            return True
    return False


def is_command(text: str) -> bool:
    return text.lstrip().startswith('{"cmd"')
