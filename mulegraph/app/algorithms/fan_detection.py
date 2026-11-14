"""Fan-in / fan-out detection.

FAN-IN  : many distinct accounts paying into one common account.
FAN-OUT : one account distributing to many distinct destinations.

Both directions compute identical evidence metrics so downstream consumers can
reason about them uniformly:

* unique incoming/outgoing accounts
* transaction count
* total amount
* time concentration (peak 60s bucket share, span, frequency)
* amount distribution (min/max/mean/stdev/CV)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import GraphConfig
from ..graph.adjacency_index import Window
from ..graph.graph_store import GraphStore
from ..graph.models import is_settled
from .common import (
    Budget,
    Pattern,
    amount_distribution,
    severity_for_score,
    stable_pattern_id,
    time_concentration,
)


@dataclass
class FanResult:
    account_id: str
    direction: str  # "IN" | "OUT"
    detected: bool
    unique_accounts: int
    transaction_count: int
    total_amount: float
    window: Window | None
    concentration: dict[str, Any]
    amount_stats: dict[str, Any]
    transaction_ids: list[str]
    counterparty_accounts: list[str]
    amounts: list[float]
    timestamps: list[float]
    thresholds: dict[str, int]
    severity: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "direction": self.direction,
            "detected": self.detected,
            "unique_accounts": self.unique_accounts,
            "transaction_count": self.transaction_count,
            "total_amount": self.total_amount,
            "window": None if self.window is None else self.window.to_dict(),
            "time_concentration": self.concentration,
            "amount_distribution": self.amount_stats,
            "thresholds": self.thresholds,
            "severity": self.severity,
            "score": round(self.score, 3),
        }


def _collect(
    store: GraphStore, account_id: str, window: Window | None, direction: str
) -> list[tuple[float, str, str, float]]:
    """(timestamp, counterparty, tx_id, amount) rows for one direction."""
    rows: list[tuple[float, str, str, float]] = []
    entries = (
        store.index.in_neighbors(account_id, window)
        if direction == "IN"
        else store.index.out_neighbors(account_id, window)
    )
    for ts, other, tx_id in entries:
        record = store.transactions.get(tx_id)
        if record is None or not record.is_settled:
            continue  # held / rejected / reversed / pending never count as flow
        rows.append((ts, other, tx_id, record.amount))
    rows.sort(key=lambda r: r[0])
    return rows


def _evaluate(
    store: GraphStore,
    account_id: str,
    window: Window | None,
    direction: str,
    config: GraphConfig,
) -> FanResult:
    rows = _collect(store, account_id, window, direction)
    counterparties = {r[1] for r in rows}
    amounts = [r[3] for r in rows]
    timestamps = [r[0] for r in rows]
    tx_ids = [r[2] for r in rows]

    concentration = time_concentration(timestamps)
    amount_stats = amount_distribution(amounts)
    thresholds = {
        "min_unique_accounts": config.fan_min_unique_accounts,
        "min_transactions": config.fan_min_transactions,
    }

    detected = (
        len(counterparties) >= thresholds["min_unique_accounts"]
        and len(rows) >= thresholds["min_transactions"]
    )

    # Transparent, rule-based score in [0, 1] (no ML involved).
    unique_score = min(1.0, len(counterparties) / max(1, thresholds["min_unique_accounts"] * 2))
    count_score = min(1.0, len(rows) / max(1, thresholds["min_transactions"] * 2))
    burst_score = float(concentration.get("peak_share") or 0.0)
    score = 0.5 * unique_score + 0.3 * count_score + 0.2 * burst_score
    if not detected:
        score *= 0.5

    return FanResult(
        account_id=account_id,
        direction=direction,
        detected=detected,
        unique_accounts=len(counterparties),
        transaction_count=len(rows),
        total_amount=round(sum(amounts), 2),
        window=window,
        concentration=concentration,
        amount_stats=amount_stats,
        transaction_ids=tx_ids,
        counterparty_accounts=sorted(counterparties),
        amounts=amounts,
        timestamps=timestamps,
        thresholds=thresholds,
        severity=severity_for_score(score),
        score=score,
    )


def detect_fan_in(
    store: GraphStore,
    account_id: str,
    window: Window | None = None,
    config: GraphConfig | None = None,
    budget: Budget | None = None,
) -> FanResult:
    """Multiple accounts transferring money into a common account."""
    cfg = config or store.config
    if budget is not None and not budget.tick():
        return _empty_fan(account_id, "IN", window, cfg)
    return _evaluate(store, account_id, window, "IN", cfg)


def detect_fan_out(
    store: GraphStore,
    account_id: str,
    window: Window | None = None,
    config: GraphConfig | None = None,
    budget: Budget | None = None,
) -> FanResult:
    """One account distributing money to many destinations."""
    cfg = config or store.config
    if budget is not None and not budget.tick():
        return _empty_fan(account_id, "OUT", window, cfg)
    return _evaluate(store, account_id, window, "OUT", cfg)


def _empty_fan(account_id: str, direction: str, window: Window | None, cfg: GraphConfig) -> FanResult:
    return FanResult(
        account_id=account_id,
        direction=direction,
        detected=False,
        unique_accounts=0,
        transaction_count=0,
        total_amount=0.0,
        window=window,
        concentration={},
        amount_stats={"count": 0, "total": 0.0},
        transaction_ids=[],
        counterparty_accounts=[],
        amounts=[],
        timestamps=[],
        thresholds={
            "min_unique_accounts": cfg.fan_min_unique_accounts,
            "min_transactions": cfg.fan_min_transactions,
        },
        severity="LOW",
        score=0.0,
    )


def fan_result_to_pattern(result: FanResult) -> Pattern | None:
    """Convert a detected fan result into an evidence Pattern."""
    if not result.detected:
        return None
    ptype = "FAN_IN" if result.direction == "IN" else "FAN_OUT"
    direction_text = (
        "Multiple accounts transferred funds into a common account."
        if result.direction == "IN"
        else "The account distributed funds to many destination accounts."
    )
    return Pattern(
        pattern_type=ptype,
        pattern_id=stable_pattern_id(ptype, result.transaction_ids),
        accounts_involved=[result.account_id, *result.counterparty_accounts],
        transaction_ids=result.transaction_ids,
        amounts=result.amounts,
        timestamps=result.timestamps,
        window=result.window,
        algorithm="fan_detection.detect_fan_" + result.direction.lower(),
        metrics={
            "unique_accounts": result.unique_accounts,
            "transaction_count": result.transaction_count,
            "total_amount": result.total_amount,
            "time_concentration": result.concentration,
            "amount_distribution": result.amount_stats,
        },
        parameters=result.thresholds,
        severity=result.severity,
        explanation=(
            f"{direction_text} "
            f"{result.unique_accounts} unique counterparties, "
            f"{result.transaction_count} settled transactions totalling "
            f"{result.total_amount} in the analysed window."
        ),
    )


def scan_fan_accounts(
    store: GraphStore,
    window: Window | None,
    config: GraphConfig | None = None,
    top_n: int = 50,
    budget: Budget | None = None,
) -> list[FanResult]:
    """Find the strongest fan-in/fan-out accounts (used by /patterns scans)."""
    cfg = config or store.config
    results: list[FanResult] = []
    for account_id, _deg in store.index.top_accounts_by_degree(limit=top_n):
        if budget is not None and not budget.tick():
            break
        for direction, detector in (("IN", detect_fan_in), ("OUT", detect_fan_out)):
            res = detector(store, account_id, window, cfg)
            if res.detected:
                results.append(res)
    results.sort(key=lambda r: r.score, reverse=True)
    return results
