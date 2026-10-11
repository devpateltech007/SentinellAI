"""The AI cache (V4): an accepted answer is reused when the same evidence is judged the
same way again, so a repeated audit costs nothing and gives the same verdict.

The key (ai.cache_key) covers everything that can change an answer: the document's
hash and extractor, or the screenshot's pixels and the picture that was sent; the
rule's wording; the model and its settings; and the prompt, schema, preparation and
validation versions. Change any of them and the answer is asked for again.

Only `accepted` answers are stored: an unsure, refused or broken answer is asked
again next time. `run --refresh-ai` skips the lookups and replaces what it finds;
the research experiment uses no cache at all. Rows live in the ai_cache table of
compliance.db and name the result they came from.
"""

import datetime
import json
from dataclasses import dataclass

from compliancelens import evidence
from compliancelens.evaluator import ai


@dataclass(frozen=True)
class Hit:
    """A stored answer, ready to be used again."""

    verdict: str
    confidence: str
    reason: str
    answer: dict
    attempts: list
    source: dict  # where it was first answered: run, rule, result row, time


class Cache:
    def __init__(self, conn):
        self.conn = conn

    def lookup(self, key: str) -> Hit | None:
        row = self.conn.execute(
            "SELECT c.*, r.run_id, r.rule_id AS source_rule FROM ai_cache c"
            " LEFT JOIN results r ON r.id = c.source_result_id WHERE c.cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        stored = json.loads(row["answer_json"])
        return Hit(
            verdict=stored["verdict"],
            confidence=stored["confidence"],
            reason=stored["reason"],
            answer=stored["answer"],
            attempts=json.loads(row["replies_json"]),
            source={
                "run": evidence.run_name(row["run_id"]) if row["run_id"] else None,
                "rule_id": row["source_rule"] or row["rule_id"],
                "result_id": row["source_result_id"],
                "cached_at": row["created_at"],
                "served_model": row["served_model"],
            },
        )

    def store(self, outcome: ai.AIOutcome, rule_id: str, result_id: int | None) -> bool:
        """Keep an accepted, freshly asked answer. Returns True if it was stored."""
        if outcome.status != ai.ACCEPTED or outcome.from_cache or not outcome.cache_key:
            return False
        served = next(
            (a.get("served_model") for a in reversed(outcome.attempts) if a.get("served_model")),
            None,
        )
        stored = {
            "verdict": outcome.verdict,
            "confidence": outcome.confidence,
            "reason": outcome.reason,
            "answer": outcome.answer,
        }
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO ai_cache (cache_key, kind, rule_id, answer_json,"
                " replies_json, provider, model, served_model, source_result_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    outcome.cache_key,
                    outcome.evidence["kind"],
                    rule_id,
                    json.dumps(stored, sort_keys=True),
                    json.dumps(outcome.attempts, sort_keys=True, default=str),
                    outcome.settings["provider"],
                    outcome.settings["model"],
                    served,
                    result_id,
                    datetime.datetime.now(datetime.UTC).isoformat(),
                ),
            )
        return True
