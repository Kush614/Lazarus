#!/usr/bin/env python3
"""Scores the current port/ against an original through the gate, without Docker.
usage: RELIC_BINARY=<path> uv run python scripts/try_gate.py"""
import os
import pathlib
import sys

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from core import gate
from core.sandbox import ProcessTarget

with ProcessTarget([sys.executable, "-m", "uvicorn", "port.app:app", "--port", "{port}", "--log-level", "error"], cwd=str(ROOT)) as t:
    print(gate.evaluate(t, 0).version.model_dump_json(indent=2))
