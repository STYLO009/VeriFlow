"""Logical investigation tools mapped onto the graph engine's real APIs.

Each tool is a ``ToolSpec``: a Pydantic ``args_schema`` (typed, bounded,
``extra="forbid"``), a read-only handler bound to a :class:`GraphClient`, a
short factual summary builder used for evidence provenance, and a LangChain
``StructuredTool`` view for model-facing tool abstractions.

Nothing here exposes code execution, SQL, shell or graph mutation - the tool
surface is a fixed, auditable whitelist.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .graph_client import GraphClient
from .summarize import summarize_payload
from .validation import (
    ToolExecutionError,
    ToolValidationError,
    validate_account_id,
    validate_account_list,
    validate_int,
    validate_profile,
    validate_transaction_id,
    validate_window,
)

logger = logging.getLogger("mulegraph.ai.tools")

WindowLiteral = Literal["5s", "30s", "5m", "1h", "24h"]
ProfileLiteral = Literal["FAST", "STANDARD", "DEEP"]


# ====================================================================== #
# tool result
# ====================================================================== #
@dataclass
class ToolResult:
    tool: str
    arguments: dict[str, Any]
    ok: bool
    data: Any = None
    error: str | None = None
    error_kind: str | None = None  # validation | execution | unknown_tool
    duration_ms: float = 0.0
    graph_version: int | None = None
    collected_at: float = field(default_factory=time.time)
    cached: bool = False
    truncated: bool = False
    provenance: str = "mulegraph.graph_engine"

    @property
    def transaction_ids(self) -> list[str]:
        ids: list[str] = []

        def walk(node: Any, key: str = "") -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if "transaction_id" in k and isinstance(v, str):
                        ids.append(v)
                    elif "transaction_ids" in k and isinstance(v, list):
                        ids.extend(str(x) for x in v)
                    else:
                        walk(v, k)
            elif isinstance(node, list):
                for item in node[:500]:
                    walk(item, key)

        walk(self.data)
        seen: list[str] = []
        for tx in ids:
            if tx not in seen:
                seen.append(tx)
        return seen

    @property
    def account_ids(self) -> list[str]:
        ids: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("account_id", "source", "destination") and isinstance(v, str):
                        ids.append(v)
                    elif k in ("accounts", "members", "accounts_involved") and isinstance(v, list):
                        ids.extend(str(x) for x in v)
                    elif k in ("nodes", "connected_accounts", "involved_accounts") and isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict) and isinstance(item.get("account_id"), str):
                                ids.append(item["account_id"])
                            elif isinstance(item, str):
                                ids.append(item)
                    else:
                        walk(v)
            elif isinstance(node, list):
                for item in node[:500]:
                    walk(item)

        walk(self.data)
        seen: list[str] = []
        for acc in ids:
            if acc not in seen:
                seen.append(acc)
        return seen

    def to_history(self) -> dict[str, Any]:
        """Compact execution record for ``tool_execution_history``."""
        return {
            "tool": self.tool,
            "arguments": {k: v for k, v in self.arguments.items()},
            "ok": self.ok,
            "error": self.error,
            "error_kind": self.error_kind,
            "duration_ms": round(self.duration_ms, 2),
            "graph_version": self.graph_version,
            "cached": self.cached,
            "collected_at": self.collected_at,
            "provenance": self.provenance,
        }


# ====================================================================== #
# argument schemas
# ====================================================================== #
class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountWindowArgs(_Args):
    account_id: str
    window: WindowLiteral = "24h"

    @field_validator("account_id")
    @classmethod
    def _acct(cls, v: Any) -> str:
        return validate_account_id(v)


class NeighborhoodArgs(AccountWindowArgs):
    hops: int = 1

    @field_validator("hops")
    @classmethod
    def _hops(cls, v: Any) -> int:
        return validate_int(v, "hops", minimum=1, maximum=4, default=1)


class HistoryArgs(AccountWindowArgs):
    page: int = 1
    page_size: int = 50

    @field_validator("page")
    @classmethod
    def _page(cls, v: Any) -> int:
        return validate_int(v, "page", minimum=1, maximum=10_000, default=1)

    @field_validator("page_size")
    @classmethod
    def _size(cls, v: Any) -> int:
        return validate_int(v, "page_size", minimum=1, maximum=100, default=50)


class TransactionArgs(_Args):
    transaction_id: str

    @field_validator("transaction_id")
    @classmethod
    def _tx(cls, v: Any) -> str:
        return validate_transaction_id(v)


class TraceArgs(_Args):
    source_account: str
    destination_account: str
    max_hops: int = 4
    window: WindowLiteral = "24h"
    min_amount: float | None = None
    chronological: bool = False
    shortest_only: bool = False

    @field_validator("source_account")
    @classmethod
    def _src(cls, v: Any) -> str:
        return validate_account_id(v, "source_account")

    @field_validator("destination_account")
    @classmethod
    def _dst(cls, v: Any) -> str:
        return validate_account_id(v, "destination_account")

    @field_validator("max_hops")
    @classmethod
    def _hops(cls, v: Any) -> int:
        return validate_int(v, "max_hops", minimum=1, maximum=6, default=4)

    @field_validator("min_amount")
    @classmethod
    def _amt(cls, v: Any) -> float | None:
        if v is None:
            return None
        try:
            value = float(v)
        except (TypeError, ValueError):
            raise ToolValidationError("min_amount", "must be a number") from None
        if value <= 0:
            raise ToolValidationError("min_amount", "must be > 0")
        return value


class CyclesArgs(_Args):
    window: WindowLiteral = "24h"
    min_length: int = 3
    max_length: int | None = None
    account_id: str | None = None

    @field_validator("min_length")
    @classmethod
    def _min(cls, v: Any) -> int:
        return validate_int(v, "min_length", minimum=2, maximum=8, default=3)

    @field_validator("max_length")
    @classmethod
    def _max(cls, v: Any) -> int | None:
        if v is None:
            return None
        return validate_int(v, "max_length", minimum=3, maximum=8)

    @field_validator("account_id")
    @classmethod
    def _acct(cls, v: Any) -> str | None:
        if v is None:
            return None
        return validate_account_id(v)


class CompareArgs(_Args):
    account_ids: list[str]
    window: WindowLiteral = "24h"

    @field_validator("account_ids")
    @classmethod
    def _accts(cls, v: Any) -> list[str]:
        return validate_account_list(v, minimum=2, maximum=5)


class EvidenceArgs(AccountWindowArgs):
    profile: ProfileLiteral = "STANDARD"

    @field_validator("profile")
    @classmethod
    def _prof(cls, v: Any) -> str:
        return validate_profile(v, default="STANDARD")


class CommunityArgs(AccountWindowArgs):
    min_size: int = 3

    @field_validator("min_size")
    @classmethod
    def _min(cls, v: Any) -> int:
        return validate_int(v, "min_size", minimum=2, maximum=50, default=3)


# ====================================================================== #
# deterministic fact builders (observed facts, no interpretation)
# ====================================================================== #
def _fact_profile(data: dict[str, Any], args: dict[str, Any]) -> str:
    if not data.get("exists", True):
        return f"Account {data.get('account_id', args.get('account_id'))} does not exist in the graph."
    activity = data.get("activity") or {}
    degrees = data.get("degrees") or {}
    return (
        f"{data.get('account_id')}: {activity.get('incoming_transactions', 0)} incoming / "
        f"{activity.get('outgoing_transactions', 0)} outgoing settled transactions in window "
        f"{data.get('window')}; in-degree {degrees.get('in_degree', 0)}, out-degree "
        f"{degrees.get('out_degree', 0)}; unique counterparties in {activity.get('unique_incoming_accounts', 0)} "
        f"/ out {activity.get('unique_outgoing_accounts', 0)}; settled amount "
        f"{data.get('settled_amount', 0)}."
    )


def _fact_neighborhood(data: dict[str, Any], args: dict[str, Any]) -> str:
    return (
        f"Neighbourhood of {data.get('account_id')} (hops={data.get('hops')}, window "
        f"{data.get('time_window')}): {data.get('node_count')} accounts, "
        f"{data.get('edge_count')} transaction edges"
        + (" [truncated]" if data.get("truncated") else "")
        + "."
    )


def _fact_history(data: dict[str, Any], args: dict[str, Any]) -> str:
    return (
        f"{data.get('account_id')} has {data.get('total_transactions')} transactions in window "
        f"{data.get('window')} (page {data.get('page')}/{data.get('total_pages')} shown); "
        f"settled amount {data.get('settled_amount')}."
    )


def _fact_transaction(data: dict[str, Any], args: dict[str, Any]) -> str:
    return (
        f"Transaction {data.get('transaction_id')}: {data.get('source_account')} -> "
        f"{data.get('destination_account')} amount {data.get('amount')} "
        f"{data.get('currency', '')} status {data.get('status')} at {data.get('created_at')}."
    )


def _fact_fan(data: dict[str, Any], args: dict[str, Any]) -> str:
    direction = data.get("direction", "IN")
    account = data.get("account_id", args.get("account_id"))
    window = args.get("window", "")
    if not data.get("detected", False):
        return f"No FAN_{direction} pattern detected for {account} in window {window}."
    unique = data.get("unique_accounts", 0)
    count = data.get("transaction_count", 0)
    total = data.get("total_amount", 0)
    tx_ids = data.get("transaction_ids") or []
    suffix = f" [{len(tx_ids)} transaction ids]" if tx_ids else ""
    return (
        f"FAN_{direction} detected on {account}: {unique} unique counterparties, "
        f"{count} transactions, total {total} (severity {data.get('severity', 'n/a')}){suffix}."
    )


def _fact_trace(data: dict[str, Any], args: dict[str, Any]) -> str:
    return (
        f"Money-flow trace {args.get('source_account')} -> {args.get('destination_account')}: "
        f"{data.get('path_count', 0)} path(s), shortest {data.get('shortest_hops')} hops"
        + (" [truncated]" if data.get("truncated") else "")
        + "."
    )


def _fact_cycles(data: dict[str, Any], args: dict[str, Any]) -> str:
    scope = f" involving {args.get('account_id')}" if args.get("account_id") else ""
    extra = ""
    if "total_cycles_in_window" in data:
        extra = f" (of {data.get('total_cycles_in_window')} cycles in window)"
    return (
        f"{data.get('cycle_count', 0)} circular transaction pattern(s){scope}{extra} "
        f"in window {data.get('time_window')}, min length {data.get('detection_parameters', {}).get('min_length')}."
    )


def _fact_temporal(data: dict[str, Any], args: dict[str, Any]) -> str:
    return (
        f"{data.get('motif_count', 0)} temporal pattern(s) involving {data.get('account_id')} "
        f"in window {data.get('time_window')}"
        + (
            f" (of {data.get('total_motifs_in_window')} in window)"
            if "total_motifs_in_window" in data
            else ""
        )
        + "."
    )


def _fact_communities(data: dict[str, Any], args: dict[str, Any]) -> str:
    membership = data.get("account_communities") or []
    if not membership:
        return (
            f"{data.get('account_id')} belongs to no community of size >= "
            f"{args.get('min_size', 3)} in window {data.get('time_window')} "
            f"({data.get('community_count', 0)} communities found)."
        )
    parts = [
        f"{c.get('community_id')} (size {c.get('size')}, internal volume "
        f"{c.get('internal_volume')}, suspicious_concentration={c.get('suspicious_concentration')})"
        for c in membership
    ]
    return f"{data.get('account_id')} is a member of: {'; '.join(parts)}."


def _fact_centrality(data: dict[str, Any], args: dict[str, Any]) -> str:
    metrics = data.get("account_metrics") or {}
    return (
        f"Centrality of {data.get('account_id')} in window {data.get('time_window')}: "
        f"{', '.join(f'{k}={v}' for k, v in metrics.items()) or 'no metrics'}; "
        f"bridge node={data.get('is_bridge_node')}."
    )


def _fact_evidence(data: dict[str, Any], args: dict[str, Any]) -> str:
    patterns = data.get("detected_patterns") or []
    risk = data.get("risk_assessment") or {}
    types = [p.get("pattern_type", "?") for p in patterns]
    return (
        f"Graph evidence for {data.get('target_account')} (profile {data.get('profile')}, window "
        f"{data.get('time_window')}): {len(patterns)} pattern(s) [{', '.join(types) or 'none'}]; "
        f"risk score {risk.get('score')} ({risk.get('severity')}); "
        f"{len(data.get('graph_evidence') or [])} evidence item(s)."
    )


def _fact_compare(data: dict[str, Any], args: dict[str, Any]) -> str:
    pairwise = data.get("pairwise") or []
    shared = sum(1 for p in pairwise if p.get("shared_counterparties"))
    return (
        f"Compared {len(data.get('accounts') or [])} accounts over window {data.get('window')}: "
        f"{shared} pair(s) share direct counterparties; "
        f"{sum(1 for p in pairwise if p.get('shared_community'))} pair(s) share a community."
    )


# ====================================================================== #
# handlers
# ====================================================================== #
def _handle_profile(args: AccountWindowArgs, client: GraphClient) -> dict[str, Any]:
    return client.account_profile(args.account_id, args.window)


def _handle_neighborhood(args: NeighborhoodArgs, client: GraphClient) -> dict[str, Any]:
    return client.neighborhood(args.account_id, args.hops, args.window)


def _handle_history(args: HistoryArgs, client: GraphClient) -> dict[str, Any]:
    return client.transaction_history(args.account_id, args.window, args.page, args.page_size)


def _handle_transaction(args: TransactionArgs, client: GraphClient) -> dict[str, Any]:
    return client.transaction_details(args.transaction_id)


def _handle_fan_in(args: AccountWindowArgs, client: GraphClient) -> dict[str, Any]:
    return client.detect_fan(args.account_id, args.window, "IN")


def _handle_fan_out(args: AccountWindowArgs, client: GraphClient) -> dict[str, Any]:
    return client.detect_fan(args.account_id, args.window, "OUT")


def _handle_trace(args: TraceArgs, client: GraphClient) -> dict[str, Any]:
    return client.trace(
        args.source_account,
        args.destination_account,
        args.max_hops,
        args.window,
        args.min_amount,
        args.chronological,
        args.shortest_only,
    )


def _handle_cycles(args: CyclesArgs, client: GraphClient) -> dict[str, Any]:
    return client.cycles(args.window, args.min_length, args.max_length, args.account_id)


def _handle_temporal(args: AccountWindowArgs, client: GraphClient) -> dict[str, Any]:
    return client.temporal_patterns(args.account_id, args.window)


def _handle_communities(args: CommunityArgs, client: GraphClient) -> dict[str, Any]:
    return client.communities(args.account_id, args.window, args.min_size)


def _handle_centrality(args: AccountWindowArgs, client: GraphClient) -> dict[str, Any]:
    return client.centrality(args.account_id, args.window)


def _handle_evidence(args: EvidenceArgs, client: GraphClient) -> dict[str, Any]:
    return client.graph_evidence(args.account_id, args.window, args.profile)


def _handle_compare(args: CompareArgs, client: GraphClient) -> dict[str, Any]:
    """Deterministic pairwise comparison composed from graph primitives."""
    accounts: list[dict[str, Any]] = []
    counterparties: dict[str, set[str]] = {}
    communities: dict[str, list[str]] = {}

    for account_id in args.account_ids:
        try:
            profile = client.account_profile(account_id, args.window)
            hood = client.neighborhood(account_id, 1, args.window)
            comm = client.communities(account_id, args.window, 3)
        except ToolExecutionError as exc:
            # a missing/failed account must not abort the whole comparison
            accounts.append({"account_id": account_id, "error": str(exc)})
            counterparties[account_id] = set()
            communities[account_id] = []
            continue
        peers: set[str] = set()
        for edge in hood.get("edges", []):
            src = edge.get("source")
            dst = edge.get("destination")
            if src == account_id and isinstance(dst, str):
                peers.add(dst)
            elif dst == account_id and isinstance(src, str):
                peers.add(src)
        counterparties[account_id] = peers
        communities[account_id] = [
            c.get("community_id", "")
            for c in (comm.get("account_communities") or [])
        ]
        activity = profile.get("activity") or {}
        accounts.append(
            {
                "account_id": account_id,
                "exists": profile.get("exists", False),
                "degrees": profile.get("degrees", {}),
                "incoming_transactions": activity.get("incoming_transactions", 0),
                "outgoing_transactions": activity.get("outgoing_transactions", 0),
                "incoming_amount": activity.get("incoming_amount", 0),
                "outgoing_amount": activity.get("outgoing_amount", 0),
                "unique_counterparties": len(peers),
                "counterparty_sample": sorted(peers)[:20],
                "community_ids": communities[account_id],
                "settled_amount": profile.get("settled_amount", 0),
            }
        )

    pairwise: list[dict[str, Any]] = []
    ids = list(args.account_ids)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            shared = sorted(counterparties.get(a, set()) & counterparties.get(b, set()))
            shared_comm = sorted(
                set(communities.get(a, [])) & set(communities.get(b, []))
            )
            pairwise.append(
                {
                    "account_a": a,
                    "account_b": b,
                    "shared_counterparties": shared,
                    "shared_counterparty_count": len(shared),
                    "shared_community": shared_comm[0] if shared_comm else None,
                    "directly_connected": b in counterparties.get(a, set())
                    or a in counterparties.get(b, set()),
                }
            )

    return {
        "window": args.window,
        "accounts": accounts,
        "pairwise": pairwise,
        "parameters": {"algorithm": "deterministic_pairwise_comparison"},
    }


# ====================================================================== #
# tool spec
# ====================================================================== #
Handler = Callable[[Any, GraphClient], dict[str, Any]]
FactBuilder = Callable[[dict[str, Any], dict[str, Any]], str]


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler
    fact_builder: FactBuilder | None = None
    tags: tuple[str, ...] = ()
    mutates_graph: bool = False  # always False: read-only by construction

    def __post_init__(self) -> None:
        if self.mutates_graph:  # pragma: no cover - guard against misuse
            raise ToolExecutionError(f"tool {self.name} would mutate the graph - refused")

    # ------------------------------------------------------------------ #
    def json_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()

    def validate_args(self, raw: Any) -> BaseModel:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ToolValidationError("arguments", "tool arguments must be an object")
        try:
            return self.args_model.model_validate(raw)
        except ValidationError as exc:
            errors = []
            for err in exc.errors():
                loc = ".".join(str(x) for x in err.get("loc", ()))
                errors.append(f"{loc or 'arguments'}: {err.get('msg', 'invalid')}")
            raise ToolValidationError("arguments", "; ".join(errors[:5])) from None

    # ------------------------------------------------------------------ #
    def invoke(
        self,
        client: GraphClient,
        raw_arguments: dict[str, Any] | None,
        char_budget: int = 14_000,
    ) -> ToolResult:
        started = time.perf_counter()
        arguments = dict(raw_arguments or {})
        try:
            args = self.validate_args(arguments)
        except ToolValidationError as exc:
            return ToolResult(
                tool=self.name,
                arguments=arguments,
                ok=False,
                error=str(exc),
                error_kind="validation",
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )

        normalised = args.model_dump(mode="json")
        try:
            data = self.handler(args, client)
        except ToolValidationError as exc:
            return ToolResult(
                tool=self.name,
                arguments=normalised,
                ok=False,
                error=str(exc),
                error_kind="validation",
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
        except (ToolExecutionError, LookupError, ValueError) as exc:
            return ToolResult(
                tool=self.name,
                arguments=normalised,
                ok=False,
                error=str(exc),
                error_kind="execution",
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001 - never leak internals to the model
            logger.exception("tool %s failed", self.name)
            return ToolResult(
                tool=self.name,
                arguments=normalised,
                ok=False,
                error=f"internal error while running {self.name}: {type(exc).__name__}",
                error_kind="execution",
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )

        _, truncated = summarize_payload(data, char_budget)
        return ToolResult(
            tool=self.name,
            arguments=normalised,
            ok=True,
            data=data,
            duration_ms=(time.perf_counter() - started) * 1000.0,
            graph_version=_safe_graph_version(client),
            truncated=truncated,
        )

    # ------------------------------------------------------------------ #
    def to_langchain(self, client: GraphClient) -> Any:
        """LangChain ``StructuredTool`` view over this spec (read-only)."""
        from langchain_core.tools import StructuredTool

        spec = self

        def _run(**kwargs: Any) -> dict[str, Any]:
            result = spec.invoke(client, kwargs)
            if not result.ok:
                return {"error": result.error, "tool": spec.name}
            return result.data if isinstance(result.data, dict) else {"result": result.data}

        return StructuredTool.from_function(
            func=_run,
            name=self.name,
            description=self.description,
            args_schema=spec.args_model,
        )


def _safe_graph_version(client: GraphClient) -> int | None:
    try:
        return client.graph_version()
    except Exception:  # noqa: BLE001 - version is metadata only
        return None


# ====================================================================== #
# the tool catalogue
# ====================================================================== #
def build_tools() -> list[ToolSpec]:
    """The fixed, read-only investigation tool catalogue."""
    return [
        ToolSpec(
            name="get_account_profile",
            description=(
                "Account summary: existence, degrees, in/out activity counts and amounts, "
                "settled volume for one account inside a time window. Start here for any "
                "new account."
            ),
            args_model=AccountWindowArgs,
            handler=_handle_profile,
            fact_builder=_fact_profile,
            tags=("profile", "account"),
        ),
        ToolSpec(
            name="get_account_neighborhood",
            description=(
                "Bounded BFS neighbourhood around an account (1-4 hops): nodes with degrees "
                "and individual transaction edges (ids, amounts, timestamps)."
            ),
            args_model=NeighborhoodArgs,
            handler=_handle_neighborhood,
            fact_builder=_fact_neighborhood,
            tags=("topology", "account"),
        ),
        ToolSpec(
            name="get_transaction_history",
            description=(
                "Paginated transaction list for an account in a time window, with amounts, "
                "counterparties, timestamps and statuses."
            ),
            args_model=HistoryArgs,
            handler=_handle_history,
            fact_builder=_fact_history,
            tags=("transactions", "account"),
        ),
        ToolSpec(
            name="get_transaction_details",
            description=(
                "Full record of a single transaction id (parties, amount, status history)."
            ),
            args_model=TransactionArgs,
            handler=_handle_transaction,
            fact_builder=_fact_transaction,
            tags=("transactions",),
        ),
        ToolSpec(
            name="detect_fan_in",
            description=(
                "Detect aggregation behaviour: many distinct senders paying this account in "
                "the window (fan-in / mule collection pattern)."
            ),
            args_model=AccountWindowArgs,
            handler=_handle_fan_in,
            fact_builder=_fact_fan,
            tags=("pattern", "mule"),
        ),
        ToolSpec(
            name="detect_fan_out",
            description=(
                "Detect distribution behaviour: this account paying many distinct receivers in "
                "the window (fan-out / mule distribution pattern)."
            ),
            args_model=AccountWindowArgs,
            handler=_handle_fan_out,
            fact_builder=_fact_fan,
            tags=("pattern", "mule"),
        ),
        ToolSpec(
            name="trace_money_flow",
            description=(
                "Trace bounded money-flow paths (1-6 hops) between two accounts, preserving "
                "transaction ids, amounts and timestamps. Structural paths only - it does not "
                "prove funds are the same money."
            ),
            args_model=TraceArgs,
            handler=_handle_trace,
            fact_builder=_fact_trace,
            tags=("flow", "multihop"),
        ),
        ToolSpec(
            name="detect_cycles",
            description=(
                "Detect circular transaction structures in a window (optionally only cycles "
                "that include a given account), with amounts, timestamps and repetition counts."
            ),
            args_model=CyclesArgs,
            handler=_handle_cycles,
            fact_builder=_fact_cycles,
            tags=("pattern", "circular"),
        ),
        ToolSpec(
            name="analyze_temporal_patterns",
            description=(
                "Temporal motifs involving an account: rapid pass-through, quick succession and "
                "other time-based transaction patterns with timing metrics."
            ),
            args_model=AccountWindowArgs,
            handler=_handle_temporal,
            fact_builder=_fact_temporal,
            tags=("pattern", "temporal"),
        ),
        ToolSpec(
            name="get_connected_communities",
            description=(
                "Community membership of an account (louvain clusters): internal volume, "
                "connectivity, repeated interactions and concentration flags."
            ),
            args_model=CommunityArgs,
            handler=_handle_communities,
            fact_builder=_fact_communities,
            tags=("community", "collective"),
        ),
        ToolSpec(
            name="get_centrality_metrics",
            description=(
                "PageRank / betweenness centrality for an account plus bridge-node status: "
                "use to find structurally important intermediaries."
            ),
            args_model=AccountWindowArgs,
            handler=_handle_centrality,
            fact_builder=_fact_centrality,
            tags=("metrics",),
        ),
        ToolSpec(
            name="compare_accounts",
            description=(
                "Deterministic comparison of 2-5 accounts: degrees, volumes, unique "
                "counterparties, shared counterparties and shared community membership."
            ),
            args_model=CompareArgs,
            handler=_handle_compare,
            fact_builder=_fact_compare,
            tags=("collective", "compare"),
        ),
        ToolSpec(
            name="get_graph_evidence",
            description=(
                "Full graph intelligence bundle for one account: detected patterns, risk "
                "assessment, connected accounts and evidence items with transaction references. "
                "Expensive - use once per account of interest, not for every account."
            ),
            args_model=EvidenceArgs,
            handler=_handle_evidence,
            fact_builder=_fact_evidence,
            tags=("evidence", "analysis"),
        ),
    ]


__all__ = [
    "AccountWindowArgs",
    "CommunityArgs",
    "CompareArgs",
    "CyclesArgs",
    "EvidenceArgs",
    "HistoryArgs",
    "NeighborhoodArgs",
    "ToolResult",
    "ToolSpec",
    "TransactionArgs",
    "TraceArgs",
    "build_tools",
]
