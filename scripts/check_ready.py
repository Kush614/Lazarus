"""What still stands between this checkout and a live run. Prints names and addresses, never values."""
import os
import pathlib
import shutil
import socket
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv
from fetch_hackkit.doctor import identity_from_seed

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from core.trust import ROLES  # noqa: E402

REQUIRED = {"META_API_KEY": "Muse Spark and Muse Code", "ASI_ONE_API_KEY": "intent routing", "AGENTVERSE_API_KEY": "registers the agents", "MONGODB_URI": "the shared ledger"}


def mongo_up() -> bool:
    uri = os.environ.get("MONGODB_URI", "")
    if not uri.startswith("mongodb://"):
        return bool(uri)
    u = urlparse(uri)
    try:
        socket.create_connection((u.hostname, u.port or 27017), timeout=2).close()
        return True
    except OSError:
        return False


missing = 0
print("Keys and services")
for k, why in REQUIRED.items():
    ok = bool(os.environ.get(k))
    missing += not ok
    print(f"  {'ok     ' if ok else 'MISSING'} {k} ({why})")
for name, ok, why in [("muse", shutil.which("muse"), "Muse Code CLI"), ("MongoDB", mongo_up(), "reachable at MONGODB_URI")]:
    missing += not ok
    print(f"  {'ok     ' if ok else 'MISSING'} {name} ({why})")
print("\nAgents")
for role in ROLES:
    seed = os.environ.get(f"AGENT_SEED_PHRASE_{role.upper()}")
    if not seed:
        missing += 1
        print(f"  MISSING seed for {role}")
        continue
    address, wallet = identity_from_seed(seed)
    print(f"  @lazarus-{role}\n    profile https://agentverse.ai/agents/details/{address}/profile\n    wallet  {wallet}")
print("\nReady." if not missing else f"\n{missing} item(s) missing.")
sys.exit(1 if missing else 0)
