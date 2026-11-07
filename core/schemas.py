"""Shared wire schemas (spec section 4). Also used as Spark structured-output formats."""
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Request(BaseModel):
    method: str
    path: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None  # str = sent raw; anything else is JSON-encoded; None = no body


class Response(BaseModel):
    status: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None


class Hypothesis(BaseModel):
    id: str
    endpoint: str
    claim: str
    status: Literal["INFERRED", "OBSERVED", "REFUTED"]
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)
    source: Literal["log", "probe", "hunt", "video"]
    created_version: int

    @model_validator(mode="after")
    def _honest(self):
        # The product's central promise, enforced at the type level.
        if self.status == "INFERRED" and self.confidence is None:
            raise ValueError("INFERRED hypothesis requires a confidence")
        if self.status in ("OBSERVED", "REFUTED") and not self.evidence:
            raise ValueError(f"{self.status} hypothesis requires evidence trace ids")
        return self


class Probe(BaseModel):
    id: str
    hypothesis_id: str
    request: Request
    prediction: Any = None
    rationale: str


class Trace(BaseModel):
    id: str
    request: Request
    response: Response
    origin: Literal["log", "probe", "hunt", "heldout"]
    target: Literal["original", "port"]


class Divergence(BaseModel):
    id: str
    input: Request
    original: Response
    port: Response
    diff: str
    found_by: str
    port_version: int
    tx_bounty: str | None = None


class StrategyEdit(BaseModel):
    rationale: str
    diff: str
    affected_endpoints: list[str]
    expected_new_hypotheses: list[str]


class PortVersion(BaseModel):
    version: int
    commit: str
    heldout_equivalence: float
    regressions: list[str]
    status: Literal["PROPOSED", "ADOPTED", "ROLLED_BACK"]
    decided_by: Literal["user", "auto"] | None = None
    parent: int | None = None
    reason: str | None = None


class HuntResult(BaseModel):
    hunter: str
    input: Request
    diverged: bool
    original: Response
    port: Response
    tx_stake: str
    tx_bounty: str | None = None
    divergence_id: str | None = None
