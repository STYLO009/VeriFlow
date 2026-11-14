"""Public surface of the algorithms package."""

from .centrality import CentralityScanResult, compute_centrality
from .common import Budget, Pattern, stable_pattern_id
from .community_detection import (
    CommunityResult,
    CommunityScanResult,
    community_for_account,
    detect_communities,
)
from .cycle_detection import CycleEvidence, CycleScanResult, cycles_to_patterns, find_cycles
from .fan_detection import (
    FanResult,
    detect_fan_in,
    detect_fan_out,
    fan_result_to_pattern,
    scan_fan_accounts,
)
from .multi_hop import MoneyFlowPath, TraceResult, trace_money_flow
from .risk_propagation import PropagationResult, propagate_risk, seeds_from_patterns
from .temporal_motifs import MotifParams, MotifScanResult, detect_temporal_motifs

__all__ = [
    "Budget",
    "CentralityScanResult",
    "CommunityResult",
    "CommunityScanResult",
    "CycleEvidence",
    "CycleScanResult",
    "FanResult",
    "MoneyFlowPath",
    "MotifParams",
    "MotifScanResult",
    "Pattern",
    "PropagationResult",
    "TraceResult",
    "community_for_account",
    "compute_centrality",
    "cycles_to_patterns",
    "detect_communities",
    "detect_fan_in",
    "detect_fan_out",
    "detect_temporal_motifs",
    "fan_result_to_pattern",
    "find_cycles",
    "propagate_risk",
    "scan_fan_accounts",
    "seeds_from_patterns",
    "stable_pattern_id",
    "trace_money_flow",
]
