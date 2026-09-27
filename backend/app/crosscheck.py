"""CORE COMPONENT 1 - Cross-Check Engine.

    compare_records(declaration, corroborating_record) -> "MATCH" | "FLAGGED" | "CORROBORATED"

A single mismatching signal can only ever produce FLAGGED (review only, no attribution).
CORROBORATED is returned only when a SECOND signal from an INDEPENDENT source (e.g. an audit)
also mismatches the declaration AND agrees with the first mismatching signal.

ASSUMPTION: the spec gives compare_records two arguments, but "corroborated" can only be
decided relative to the first mismatching signal, so there are two optional keyword args:
`flagged_against` (the first signal) and `dimension` ("QUANTITY" | "STREAM").
"""
from __future__ import annotations

from typing import Optional

from .config import QUANTITY_TOLERANCE, SEGREGATED_SHARE_THRESHOLD

MATCH = "MATCH"
FLAGGED = "FLAGGED"
CORROBORATED = "CORROBORATED"

WORKER_SOURCE = "WORKER_DECLARATION"


class IndependenceError(ValueError):
    """Raised when a 'corroborating' signal is not independent of the ones it is meant to check."""


def declared_stream(segregated: int, total: int) -> str:
    share = segregated / total if total else 0.0
    return "SEGREGATED" if share >= SEGREGATED_SHARE_THRESHOLD else "MIXED"


def quantity_mismatch(declared: Optional[int], observed: Optional[int], tol: float = QUANTITY_TOLERANCE) -> bool:
    if declared is None or observed is None:
        return False
    return abs(observed - declared) > tol * max(declared, 1)


def find_mismatches(declaration: dict, record: dict, tol: float = QUANTITY_TOLERANCE) -> list[str]:
    """Which dimensions of `record` disagree with the worker's declaration."""
    out: list[str] = []
    if quantity_mismatch(declaration.get("quantity"), record.get("quantity"), tol):
        out.append("QUANTITY")
    # STREAM: worker declared a (mostly) segregated load but the other party says it is unacceptable.
    # A mixed load rejected by a facility is consistent with the declaration -> not a mismatch.
    if declaration.get("stream") == "SEGREGATED" and record.get("condition") == "UNACCEPTABLE":
        out.append("STREAM")
    return out


def signals_agree(dimension: str, first: dict, second: dict, tol: float = QUANTITY_TOLERANCE) -> bool:
    """Do two independent signals tell the same story on this dimension?"""
    if dimension == "QUANTITY":
        a, b = first.get("quantity"), second.get("quantity")
        if a is None or b is None:
            return False
        return abs(a - b) <= tol * max(a, b, 1)
    if dimension == "STREAM":
        return first.get("condition") == second.get("condition") == "UNACCEPTABLE"
    return False


def compare_records(
    declaration: dict,
    corroborating_record: dict,
    *,
    flagged_against: Optional[dict] = None,
    dimension: Optional[str] = None,
    tol: float = QUANTITY_TOLERANCE,
) -> str:
    mismatches = find_mismatches(declaration, corroborating_record, tol)

    # Mode 1 - first signal vs the declaration: can only MATCH or FLAG. Never attribute.
    if flagged_against is None:
        return FLAGGED if mismatches else MATCH

    # Mode 2 - second signal, checked against the declaration AND the first signal.
    src = corroborating_record.get("source")
    if not src or src in (WORKER_SOURCE, flagged_against.get("source")):
        raise IndependenceError(
            f"Corroborating signal must come from a source independent of the worker and of "
            f"'{flagged_against.get('source')}'; got '{src}'."
        )
    if dimension is None:
        raise ValueError("dimension is required when corroborating")
    if dimension not in mismatches:
        return MATCH  # the second signal sides with the declaration: the first flag is not confirmed
    return CORROBORATED if signals_agree(dimension, flagged_against, corroborating_record, tol) else FLAGGED
