"""Unified graph intelligence service.

``GraphAnalyzer`` coordinates every graph algorithm behind one call:

    analyzer.analyze_account("ACC-101", window="5m", profile="STANDARD")

Design principles
-----------------
* **Profile-driven execution** - not every algorithm runs on every call:

  - ``FAST``      : fan-in/fan-out, neighbourhood facts, risk triage (streaming path)
  - ``STANDARD``  : + cycles, temporal motifs, propagation, flow tracing
  - ``DEEP``      : + community detection and centrality (cached, background-refreshed)

* **Budgets** - every run gets a wall-clock/visit budget so the API cannot
  hang on pathological graphs.
* **Caches** - expensive community/centrality results are refreshed in a
  background thread and reused; they are never recomputed per transaction.
* **Evidence** - outputs separate graph facts, detected patterns and risk
  interpretations, all with real transaction ids.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..algorithms.centrality import CentralityScanResult, compute_centrality
from ..algorithms.common import Budget, Pattern
from ..algorithms.community_detection import (
    CommunityScanResult,
    community_for_account,
    detect_communities,
)
from ..algorithms.cycle_detection import CycleScanResult, cycles_to_patterns, find_cycles
from ..algorithms.fan_detection import FanResult, detect_fan_in, detect_fan_out, fan_result_to_pattern
from ..algorithms.multi_hop import TraceResult, trace_money_flow
from ..algorithms.risk_propagation import PropagationResult, propagate_risk, seeds_from_patterns
from ..algorithms.temporal_motifs import MotifScanResult, detect_temporal_motifs
from ..graph.adjacency_index import Window
from ..graph.graph_store import GraphStore
from ..graph.models import format_timestamp, is_settled
from .explainability import (
    build_evidence_bundle,
    describe_transaction_ids,
    evidence_digest,
    graph_fact,
)
from .risk_engine import RiskAssessment, assess, assessment_evidence
from .subgraph_extractor import SubgraphView, extract_subgraph

logger = logging.getLogger("mulegraph.analyzer")

_ENGINE_VERSION = "1"


class AnalysisProfile(str, Enum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


@dataclass
class _CacheEntry:
    value: Any
    computed_at: float
    refresh_in_flight: bool = False

    def age(self) -> float:
        return time.time() - self.computed_at


@dataclass
class AnalysisResult:
    analysis_id: str
    status: str
    target_account: str | None
    target_transaction: str | None
    time_window: str
    profile: str
    graph_summary: dict[str, Any]
    detected_patterns: list[dict[str, Any]]
    money_flow_paths: list[dict[str, Any]]
    communities: list[dict[str, Any]]
    centrality_metrics: dict[str, Any]
    connected_accounts: list[dict[str, Any]]
    graph_evidence: list[dict[str, Any]]
    risk_assessment: dict[str, Any]
    analysis_metadata: dict[str, Any]
    subgraph: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "analysis_id": self.analysis_id,
            "analysis_status": self.status,
            "target_account": self.target_account,
            "target_transaction": self.target_transaction,
            "time_window": self.time_window,
            "profile": self.profile,
            "graph_summary": self.graph_summary,
            "detected_patterns": self.detected_patterns,
            "money_flow_paths": self.money_flow_paths,
            "communities": self.communities,
            "centrality_metrics": self.centrality_metrics,
            "connected_accounts": self.connected_accounts,
            "graph_evidence": self.graph_evidence,
            "risk_assessment": self.risk_assessment,
            "analysis_metadata": self.analysis_metadata,
        }
        if self.subgraph is not None:
            payload["subgraph"] = self.subgraph
        return payload


class GraphAnalyzer:
    """Coordinates all graph algorithms into one structured intelligence result."""

    def __init__(self, store: GraphStore, executor: ThreadPoolExecutor | None = None) -> None:
        self.store = store
        self.config = store.config
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="mulegraph-bg"
        )
        self._communities: dict[str, _CacheEntry] = {}
        self._centrality: dict[str, _CacheEntry] = {}
        self._cache_lock = threading.Lock()
        self._analysis_counter = itertools.count(1)

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def analyze_account(
        self,
        account_id: str,
        window: str = "5m",
        profile: str | AnalysisProfile | None = None,
        reference: float | None = None,
        include_subgraph: bool = False,
        connected_limit: int = 25,
    ) -> AnalysisResult:
        """Run the analysis pipeline for one account."""
        profile = AnalysisProfile(profile or self.config.default_profile)
        started = time.perf_counter()
        window_name = window
        resolved = Window.preset(window, reference)
        budget = self._budget_for(profile)
        algorithms: list[str] = []
        notes: list[str] = []

        if not self.store.has_account(account_id):
            return self._not_found(account_id, window_name, profile, started)

        # --- stage 1: neighbourhood facts --------------------------------
        subgraph = None
        if include_subgraph or profile != AnalysisProfile.FAST:
            hops = 1 if profile == AnalysisProfile.STANDARD else 2
            subgraph = extract_subgraph(
                self.store, account_id, hops=hops, window=resolved, max_nodes=300
            )
            algorithms.append("subgraph_extractor.extract_subgraph")

        facts: list[Any] = []
        summary = self._graph_summary(account_id, resolved)
        facts.append(
            graph_fact(
                label="ACCOUNT_ACTIVITY",
                details=summary,
                explanation=(
                    f"Observed {summary['incoming_transactions']} incoming and "
                    f"{summary['outgoing_transactions']} outgoing settled transactions "
                    f"for {account_id} in the selected window."
                ),
                transaction_ids=summary.pop("_transaction_ids", [])[:50],
            )
        )

        # --- stage 2: fan detection (all profiles) -----------------------
        fan_in = detect_fan_in(self.store, account_id, resolved, budget=budget)
        fan_out = detect_fan_out(self.store, account_id, resolved, budget=budget)
        algorithms += ["fan_detection.detect_fan_in", "fan_detection.detect_fan_out"]

        patterns: list[Pattern] = []
        for fan in (fan_in, fan_out):
            pattern = fan_result_to_pattern(fan)
            if pattern is not None:
                patterns.append(pattern)

        # --- stage 3: heavier detectors (STANDARD / DEEP) ----------------
        cycle_scan: CycleScanResult | None = None
        motif_scan: MotifScanResult | None = None
        propagation: PropagationResult | None = None
        trace: TraceResult | None = None
        community_scan: CommunityScanResult | None = None
        centrality_scan: CentralityScanResult | None = None

        if profile in (AnalysisProfile.STANDARD, AnalysisProfile.DEEP):
            cycle_scan = find_cycles(self.store, window=resolved, budget=budget)
            algorithms.append("cycle_detection.find_cycles")
            patterns.extend(cycles_to_patterns(cycle_scan))
            if budget.exhausted:
                notes.append(f"cycle detection stopped early: {budget.exhausted_reason}")

        if profile in (AnalysisProfile.STANDARD, AnalysisProfile.DEEP) and budget.tick():
            motif_scan = detect_temporal_motifs(self.store, resolved, budget=budget)
            algorithms.append("temporal_motifs.detect_temporal_motifs")
            patterns.extend(motif_scan.patterns)

        if profile == AnalysisProfile.DEEP and budget.tick():
            community_scan = self._communities_for(resolved)
            algorithms.append("community_detection.detect_communities")
            centrality_scan = self._centrality_for(resolved)
            algorithms.append("centrality.compute_centrality")

        # --- stage 4: risk propagation from window-level evidence ---------
        propagation_score: float | None = None
        if profile in (AnalysisProfile.STANDARD, AnalysisProfile.DEEP) and budget.tick():
            seeds = self._seeds_for_account(account_id, resolved, budget)
            if seeds:
                propagation = propagate_risk(
                    self.store, seeds, window=resolved, budget=budget
                )
                algorithms.append("risk_propagation.propagate_risk")
                for node in propagation.nodes:
                    if node.account_id == account_id:
                        propagation_score = node.risk_score
                        break

        # --- stage 5: money-flow tracing ----------------------------------
        if profile == AnalysisProfile.DEEP and budget.tick():
            trace = self._trace_counterparties(account_id, resolved, budget)
            if trace is not None:
                algorithms.append("multi_hop.trace_money_flow")

        # --- stage 6: connected accounts ----------------------------------
        connected = self._connected_accounts(account_id, resolved, limit=connected_limit)
        algorithms.append("graph_store.neighborhood")

        # --- stage 7: risk triage ------------------------------------------
        community_suspicious = False
        if community_scan is not None:
            member = community_for_account(community_scan, account_id)
            community_suspicious = bool(member and member.suspicious)
        is_bridge = bool(
            centrality_scan is not None and account_id in centrality_scan.bridge_nodes
        )
        risk: RiskAssessment = assess(
            account_id,
            self.store,
            fan_in=fan_in,
            fan_out=fan_out,
            patterns=patterns,
            propagation_score=propagation_score,
            community_suspicious=community_suspicious,
            is_bridge=is_bridge,
        )
        algorithms.append("risk_engine.assess")

        # --- evidence ------------------------------------------------------
        interpretations = [assessment_evidence(risk)]
        if propagation is not None:
            target_nodes = [n for n in propagation.nodes if n.account_id == account_id]
            if target_nodes:
                from .explainability import risk_interpretation

                interpretations.append(
                    risk_interpretation(
                        label="PROPAGATED_ASSOCIATION",
                        details=target_nodes[0].to_dict(),
                        explanation=target_nodes[0].explanation,
                        source="risk_propagation.propagate_risk",
                    )
                )
        evidence = build_evidence_bundle(
            facts, patterns, interpretations, anchor=f"{account_id}-{next(self._analysis_counter):04d}"
        )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        metadata = {
            "algorithms_executed": sorted(set(algorithms)),
            "execution_time_ms": round(elapsed_ms, 2),
            "graph_version": self.store.version,
            "engine_version": _ENGINE_VERSION,
            "budget": budget.to_dict(),
            "notes": notes,
            "evidence_digest": evidence_digest(evidence),
            "generated_at": format_timestamp(time.time()),
            "cache_status": self._cache_status(),
        }

        return AnalysisResult(
            analysis_id=f"GRAPH-{uuid.uuid4().hex[:8].upper()}",
            status="completed" if not budget.exhausted else "completed_partial",
            target_account=account_id,
            target_transaction=None,
            time_window=window_name,
            profile=profile.value,
            graph_summary=summary,
            detected_patterns=[p.to_dict() for p in patterns],
            money_flow_paths=[] if trace is None else [p.to_dict() for p in trace.paths],
            communities=[] if community_scan is None else [c.to_dict() for c in community_scan.communities],
            centrality_metrics={} if centrality_scan is None else centrality_scan.to_dict(),
            connected_accounts=connected,
            graph_evidence=evidence,
            risk_assessment=risk.to_dict(),
            analysis_metadata=metadata,
            subgraph=None if subgraph is None else subgraph.to_dict(),
        )

    def analyze_transaction(
        self,
        transaction_id: str,
        profile: str | AnalysisProfile | None = None,
        window: str = "5m",
        include_subgraph: bool = False,
    ) -> AnalysisResult | None:
        """Analyse the accounts around one specific transaction."""
        record = self.store.get_transaction(transaction_id)
        if record is None:
            return None
        # anchor the window at the transaction time (works for historical events)
        result = self.analyze_account(
            record.destination_account,
            window=window,
            profile=profile,
            reference=record.created_at,
            include_subgraph=include_subgraph,
        )
        result.target_transaction = transaction_id
        result.graph_summary["related_transaction"] = record.to_dict()
        result.graph_summary["settled"] = record.is_settled
        return result

    # ------------------------------------------------------------------ #
    # stage helpers
    # ------------------------------------------------------------------ #
    def _budget_for(self, profile: AnalysisProfile) -> Budget:
        if profile == AnalysisProfile.DEEP:
            return Budget.with_timeout_ms(
                self.config.deep_timeout_ms, self.config.max_traversal_nodes
            )
        if profile == AnalysisProfile.FAST:
            return Budget.with_timeout_ms(
                min(self.config.analysis_timeout_ms, 500.0), 5_000
            )
        return Budget.with_timeout_ms(
            self.config.analysis_timeout_ms, self.config.max_traversal_nodes
        )

    def _graph_summary(self, account_id: str, window: Window) -> dict[str, Any]:
        incoming = self.store.index.in_neighbors(account_id, window)
        outgoing = self.store.index.out_neighbors(account_id, window)
        settled_in = [e for e in incoming if self._is_settled_tx(e[2])]
        settled_out = [e for e in outgoing if self._is_settled_tx(e[2])]
        nodes, edge_rows = self.store.neighborhood(account_id, hops=1, window=window, limit=1000)
        return {
            "nodes": len(nodes),
            "edges": len(edge_rows),
            "incoming_transactions": len(settled_in),
            "outgoing_transactions": len(settled_out),
            "non_settled_transactions": (len(incoming) + len(outgoing))
            - (len(settled_in) + len(settled_out)),
            "unique_incoming_accounts": len({e[1] for e in settled_in}),
            "unique_outgoing_accounts": len({e[1] for e in settled_out}),
            "incoming_amount": round(
                sum(self.store.transactions[t].amount for _, _, t in settled_in), 2
            ),
            "outgoing_amount": round(
                sum(self.store.transactions[t].amount for _, _, t in settled_out), 2
            ),
            "_transaction_ids": [t for _, _, t in incoming + outgoing],
        }

    def _is_settled_tx(self, tx_id: str) -> bool:
        rec = self.store.transactions.get(tx_id)
        return rec is not None and rec.is_settled

    def _connected_accounts(
        self, account_id: str, window: Window, limit: int = 25
    ) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for direction, entries in (
            ("IN", self.store.index.in_neighbors(account_id, window)),
            ("OUT", self.store.index.out_neighbors(account_id, window)),
        ):
            for ts, other, tx_id in entries:
                rec = self.store.transactions.get(tx_id)
                if rec is None:
                    continue
                row = rows.setdefault(
                    other,
                    {
                        "account_id": other,
                        "directions": set(),
                        "transactions": 0,
                        "settled_transactions": 0,
                        "total_amount": 0.0,
                        "last_timestamp": 0.0,
                        "transaction_ids": [],
                        "settled": True,
                    },
                )
                row["directions"].add(direction)
                row["transactions"] += 1
                row["last_timestamp"] = max(row["last_timestamp"], ts)
                if len(row["transaction_ids"]) < 10:
                    row["transaction_ids"].append(tx_id)
                if rec.is_settled:
                    row["settled_transactions"] += 1
                    row["total_amount"] += rec.amount
                else:
                    row["settled"] = False
        result = []
        for row in rows.values():
            row["directions"] = sorted(row["directions"])
            row["total_amount"] = round(row["total_amount"], 2)
            result.append(row)
        result.sort(key=lambda r: (r["total_amount"], r["transactions"]), reverse=True)
        return result[:limit]

    def _seeds_for_account(
        self, target: str, window: Window, budget: Budget
    ) -> dict[str, float]:
        """Find other high-severity accounts in the window to propagate from."""
        from ..algorithms.fan_detection import scan_fan_accounts

        seeds: dict[str, float] = {}
        fans = scan_fan_accounts(self.store, window, top_n=25, budget=budget)
        for fan in fans:
            if fan.account_id == target or not fan.detected or fan.severity not in ("HIGH", "CRITICAL"):
                continue
            seeds[fan.account_id] = max(seeds.get(fan.account_id, 0.0), 0.9)
        cycle_scan = find_cycles(self.store, window=window, budget=budget)
        for cycle in cycle_scan.cycles:
            if target in cycle.accounts:
                continue
            for account in cycle.accounts:
                if len(cycle.accounts) >= 4:
                    seeds[account] = max(seeds.get(account, 0.0), 0.7)
        return seeds

    def _trace_counterparties(
        self, account_id: str, window: Window, budget: Budget
    ) -> TraceResult | None:
        """Trace flow from the target to its largest counterparties."""
        connected = self._connected_accounts(account_id, window, limit=2)
        if not connected:
            return None
        destination = connected[0]["account_id"]
        if destination == account_id:
            return None
        return trace_money_flow(
            self.store, account_id, destination, max_hops=3, window=window, budget=budget
        )

    # ------------------------------------------------------------------ #
    # cached expensive analysis
    # ------------------------------------------------------------------ #
    def _cache_status(self) -> dict[str, Any]:
        with self._cache_lock:
            return {
                "communities": {k: round(v.age(), 1) for k, v in self._communities.items()},
                "centrality": {k: round(v.age(), 1) for k, v in self._centrality.items()},
            }

    def _communities_for(self, window: Window) -> CommunityScanResult:
        return self._get_or_refresh(
            self._communities,
            window,
            self.config.community_refresh_seconds,
            lambda: detect_communities(self.store, window),
            lambda w: detect_communities(self.store, w),
        )

    def _centrality_for(self, window: Window) -> CentralityScanResult:
        return self._get_or_refresh(
            self._centrality,
            window,
            self.config.centrality_refresh_seconds,
            lambda: compute_centrality(self.store, window),
            lambda w: compute_centrality(self.store, w),
        )

    def _get_or_refresh(
        self,
        cache: dict[str, _CacheEntry],
        window: Window,
        ttl_seconds: float,
        sync_compute: Any,
        bg_compute: Any,
    ) -> Any:
        key = f"{int(window.start)}:{int(window.end)}"
        with self._cache_lock:
            entry = cache.get(key)
            stale = entry is None or entry.age() > ttl_seconds
            if not stale:
                return entry.value
            if entry is not None and not entry.refresh_in_flight:
                # serve stale value, refresh in background
                if self.config.enable_background_analysis:
                    entry.refresh_in_flight = True
                    future: Future = self._executor.submit(
                        self._background_refresh, cache, key, window, bg_compute
                    )
                    future.add_done_callback(
                        lambda _f, _c=cache, _k=key: _clear_refresh_flag(_c, _k)
                    )
                    return entry.value
                # background disabled -> refresh synchronously
                value = sync_compute()
                cache[key] = _CacheEntry(value=value, computed_at=time.time())
                return value
            if entry is not None:
                return entry.value
            # cold start: must compute synchronously
            value = sync_compute()
            cache[key] = _CacheEntry(value=value, computed_at=time.time())
            return value

    def _background_refresh(
        self, cache: dict[str, _CacheEntry], key: str, window: Window, compute: Any
    ) -> None:
        try:
            value = compute(window)
            with self._cache_lock:
                cache[key] = _CacheEntry(value=value, computed_at=time.time())
        except Exception:  # pragma: no cover - background failures never break requests
            logger.exception("background analysis refresh failed")

    # ------------------------------------------------------------------ #
    # misc
    # ------------------------------------------------------------------ #
    def _not_found(
        self, account_id: str, window: str, profile: AnalysisProfile, started: float
    ) -> AnalysisResult:
        return AnalysisResult(
            analysis_id=f"GRAPH-{uuid.uuid4().hex[:8].upper()}",
            status="account_not_found",
            target_account=account_id,
            target_transaction=None,
            time_window=window,
            profile=profile.value,
            graph_summary={"nodes": 0, "edges": 0, "incoming_transactions": 0, "outgoing_transactions": 0},
            detected_patterns=[],
            money_flow_paths=[],
            communities=[],
            centrality_metrics={},
            connected_accounts=[],
            graph_evidence=[],
            risk_assessment={"account_id": account_id, "score": 0.0, "severity": "LOW", "signals": []},
            analysis_metadata={
                "algorithms_executed": [],
                "execution_time_ms": round((time.perf_counter() - started) * 1000, 2),
                "graph_version": self.store.version,
                "engine_version": _ENGINE_VERSION,
                "notes": [f"account {account_id} not present in graph"],
            },
        )

    def health(self) -> dict[str, Any]:
        stats = self.store.stats()
        return {
            "status": "healthy",
            "graph_version": stats["graph_version"],
            "nodes": stats["nodes"],
            "edges": stats["edges"],
            "cache_status": self._cache_status(),
        }

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def _clear_refresh_flag(cache: dict[str, _CacheEntry], key: str) -> None:
    entry = cache.get(key)
    if entry is not None:
        entry.refresh_in_flight = False
