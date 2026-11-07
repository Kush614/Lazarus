"""Mongo collections and indexes (spec 5.3). Survives restart; callers pass the db."""
import os

from pymongo import ASCENDING, MongoClient


def connect(uri: str | None = None, name: str = "lazarus"):
    db = MongoClient(uri or os.environ["MONGODB_URI"])[name]
    ensure_indexes(db)
    return db


def ensure_indexes(db) -> None:
    for coll, keys in {
        "hypotheses": ["id", "endpoint", "status", "created_version"],
        "traces": ["id", "origin", "target"],
        "probes": ["hypothesis_id"],
        "divergences": ["port_version", "found_by"],
        "port_versions": ["version", "status"],
        "strategy_versions": ["version"],
        "hunts": ["hunter", "tx_stake"],
        "immune_memory": ["heldout_id", "first_matched_version"],
    }.items():
        for k in keys:
            db[coll].create_index([(k, ASCENDING)])
    db.payments.create_index([("tx_hash", ASCENDING)], unique=True)
    # One bounty per distinct input; otherwise one divergence can be re-claimed forever.
    db.divergences.create_index([("input_hash", ASCENDING), ("port_version", ASCENDING)], unique=True, sparse=True)


def immune_ids(db) -> set[str]:
    return {d["heldout_id"] for d in db.immune_memory.find({}, {"heldout_id": 1})}


def remember_matches(db, matched_ids, version: int) -> None:
    for i in matched_ids:
        db.immune_memory.update_one({"heldout_id": i}, {"$setOnInsert": {"first_matched_version": version}}, upsert=True)


def next_id(db, prefix: str, width: int = 4) -> str:
    doc = db.counters.find_one_and_update({"_id": prefix}, {"$inc": {"n": 1}}, upsert=True, return_document=True)
    return f"{prefix}-{doc['n']:0{width}d}"


def latest_adopted(db):
    return db.port_versions.find_one({"status": "ADOPTED"}, sort=[("version", -1)])
