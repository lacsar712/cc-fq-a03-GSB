"""Server-side stage timing and timeout-gate configuration.

The toy FASTQ workload finishes in microseconds, which would make every stage
read 0 ms and make a millisecond gate impossible to exercise. Each actor
therefore declares a small, deterministic *simulated processing latency* that
the runner always incurs while measuring real wall-clock time around the
actor. The numbers below are genuine measured server-side durations — the
latency only keeps the demo workload non-instantaneous.

All durations are integer milliseconds; the gate comparison and the duration
values are computed on the server and returned by the API. The frontend never
estimates them.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ActorTimeoutConfig
from app.pipeline.actors import ACTOR_CHAIN

# Generous per-actor default ceilings (ms). Normal runs stay well under them.
DEFAULT_ACTOR_TIMEOUTS: dict[str, int] = {
    "ParseActor": 2000,
    "QualityHistActor": 2000,
    "NContentActor": 2000,
    "ReportActor": 2000,
}

# Deterministic latency (ms) the runner awaits inside each stage's measured window.
SIMULATED_STAGE_LATENCY_MS: dict[str, int] = {
    "ParseActor": 12,
    "QualityHistActor": 18,
    "NContentActor": 10,
    "ReportActor": 6,
}

STAGE_ORDER: list[str] = [cls.name for cls in ACTOR_CHAIN]


def seed_default_timeouts(db: Session) -> None:
    """Idempotently create a config row for every known actor."""
    existing = {row.actor_name for row in db.query(ActorTimeoutConfig).all()}
    changed = False
    for name in STAGE_ORDER:
        if name not in existing:
            db.add(
                ActorTimeoutConfig(
                    actor_name=name,
                    timeout_ms=DEFAULT_ACTOR_TIMEOUTS[name],
                    updated_by="system",
                )
            )
            changed = True
    if changed:
        db.commit()


def load_timeout_map(db: Session) -> dict[str, int | None]:
    """Return the currently persisted ceiling per actor (None if unset)."""
    seed_default_timeouts(db)
    rows = db.query(ActorTimeoutConfig).all()
    ceilings: dict[str, int | None] = {name: None for name in STAGE_ORDER}
    for row in rows:
        ceilings[row.actor_name] = row.timeout_ms
    return ceilings
