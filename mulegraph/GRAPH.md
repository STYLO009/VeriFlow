# MuleGraph — Graph Intelligence Engine

A production-oriented, **AI-ready** graph intelligence engine for real-time UPI
money-mule and financial-collusion detection.

This repository contains **only the graph component**: graph construction,
temporal indexing, detection algorithms, evidence extraction, a FastAPI service,
a broker-agnostic streaming processor, deterministic synthetic data, tests and
measured benchmarks. It contains **no machine learning, no GNNs, no LLM/AI
provider integrations and no frontend** — it produces structured JSON evidence
that any downstream AI system can consume.

---

## 1. Project structure

```
mulegraph/
├── app/
│   ├── main.py                     # FastAPI app factory, DI wiring, error handlers
│   ├── config.py                   # env-based settings (MULEGRAPH_*), window presets
│   │
│   ├── graph/
│   │   ├── models.py               # TransactionEvent, TransactionRecord, statuses
│   │   ├── adjacency_index.py      # adjacency + bisect time indexes, Window
│   │   ├── graph_store.py          # MultiDiGraph store, dedupe, status transitions
│   │   ├── temporal_graph.py       # windowed views, historical queries, activity
│   │   └── builder.py              # single write path (validate/dedupe/ingest)
│   │
│   ├── algorithms/
│   │   ├── common.py               # Budget, Pattern, stats helpers, severity bands
│   │   ├── fan_detection.py        # fan-in / fan-out + evidence metrics
│   │   ├── cycle_detection.py      # bounded canonical-start DFS, repeats
│   │   ├── multi_hop.py            # bounded BFS money-flow tracing
│   │   ├── temporal_motifs.py      # fan-in→fan-out, rapid pass-through, chains
│   │   ├── community_detection.py  # Louvain + internal/external volume metrics
│   │   ├── centrality.py           # degrees, PageRank (no-scipy fallback), bridges
│   │   └── risk_propagation.py     # bounded, decaying, explainable propagation
│   │
│   ├── intelligence/
│   │   ├── graph_analyzer.py       # unified service, FAST/STANDARD/DEEP profiles
│   │   ├── risk_engine.py          # transparent rule-based scoring (no ML)
│   │   ├── subgraph_extractor.py   # bounded JSON-serialisable neighbourhoods
│   │   └── explainability.py       # evidence model: FACT / PATTERN / INTERPRETATION
│   │
│   ├── streaming/
│   │   ├── event_processor.py      # validate→dedupe→ingest→analyse→publish
│   │   ├── window_manager.py       # O(1) sliding counters (5s…24h)
│   │   └── consumer.py             # pluggable sources + run_stream (Kafka optional)
│   │
│   ├── storage/
│   │   └── __init__.py             # TransactionRepository abstraction, JSONL replay
│   │
│   ├── simulator/
│   │   └── synthetic.py            # seeded generator: normal + attack scenarios
│   │
│   ├── api/
│   │   ├── routes.py               # all /api/v1/graph endpoints
│   │   └── schemas.py              # Pydantic request/response models
│   │
│   └── tests/                      # 107 tests (unit + integration + performance)
│
├── scripts/
│   ├── benchmark.py                # measured 50/100/500 TPS benchmark
│   ├── run_simulator.py            # local synthetic streaming demo (no broker)
│   └── capture_examples.py         # seeds demo data, captures real API responses
│
├── docs/example_responses/         # actual captured API responses (JSON)
├── requirements.txt
├── pytest.ini
└── README.md
```

### Core graph representation

* **`networkx.MultiDiGraph`** — every account is a node, **every transaction is
  its own directed edge** keyed by `transaction_id`.
* Multiple transactions between the same pair are **never collapsed**; edge
  attributes keep `amount`, `timestamp`, `status`, `settled`, `status_history`.
* Parallel **adjacency + time indexes** (`bisect` range scans) give O(log n)
  windowed neighbourhood queries without graph copies.
* All updates are **incremental and thread-safe** — the graph is never rebuilt
  per transaction (a rebuild path exists only for disaster recovery from
  durable events).

### Transaction state handling

| Status                   | Counts as money movement? |
|--------------------------|---------------------------|
| `COMPLETED`              | ✅ yes                     |
| `PENDING`                | ❌ no (in-flight)          |
| `REJECTED`               | ❌ no                      |
| `REVERSED`               | ❌ no (edge kept as evidence) |
| `HELD_FOR_VERIFICATION`  | ❌ no                      |

Status updates preserve the **original event** (`record.original_event`,
edge `timestamp` never changes, full `history` retained).

---

## 2. Installation (PowerShell)

```powershell
cd C:\HACKMATRIX\mulegraph

# create virtualenv (Python 3.11+; tested on 3.13)
py -3.13 -m venv .venv          # or: uv venv --python 3.13 .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
# or without pip activation:
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

Only 5 runtime dependencies: `networkx`, `fastapi`, `uvicorn`, `pydantic`,
`httpx` (+ `pytest` for tests).

---

## 3. Execution commands

```powershell
# --- API server ---
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# interactive docs: http://127.0.0.1:8000/docs

# --- tests (107) ---
.\.venv\Scripts\python.exe -m pytest -q                 # all
.\.venv\Scripts\python.exe -m pytest -q -m "not performance"
.\.venv\Scripts\python.exe -m pytest -q -m performance  # measured perf tests

# --- benchmarks (real measurements, never fabricated) ---
.\.venv\Scripts\python.exe scripts\benchmark.py --tps 50  --duration 10
.\.venv\Scripts\python.exe scripts\benchmark.py --tps 100 --duration 10
.\.venv\Scripts\python.exe scripts\benchmark.py --tps 500 --duration 6   # stress
.\.venv\Scripts\python.exe scripts\benchmark.py --tps 50 --json          # raw JSON

# --- local synthetic streaming demo (no Kafka needed) ---
.\.venv\Scripts\python.exe scripts\run_simulator.py --events 500 --tps 50
.\.venv\Scripts\python.exe scripts\run_simulator.py --events 200 --json

# --- regenerate example responses (server must be running) ---
.\.venv\Scripts\python.exe scripts\capture_examples.py
```

---

## 4. API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/graph/analyze` | Full analysis (profiles FAST/STANDARD/DEEP) |
| POST | `/api/v1/graph/transaction` | Ingest one event or a batch (≤1000) |
| GET  | `/api/v1/graph/account/{id}` | Account summary + windowed activity |
| GET  | `/api/v1/graph/account/{id}/neighborhood` | Bounded subgraph extraction |
| GET  | `/api/v1/graph/account/{id}/patterns` | Detected patterns (paginated) |
| GET  | `/api/v1/graph/account/{id}/transactions` | Transactions (paginated) |
| GET  | `/api/v1/graph/trace/{src}/{dst}` | Multi-hop money-flow tracing |
| GET  | `/api/v1/graph/cycles` | Circular transaction detection |
| GET  | `/api/v1/graph/communities` | Community detection (cached) |
| GET  | `/api/v1/graph/metrics` | Centrality metrics (cached) |
| GET  | `/api/v1/graph/health` | Health + cache status |
| GET  | `/api/v1/graph/stats` | Store statistics |

Common query params: `window` ∈ `5s | 30s | 5m | 1h | 24h`, pagination
(`page`, `page_size` ≤ 100), structured errors:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "Request validation failed", "detail": [...]}}
```

### Analysis profiles

| Profile | Runs | Typical use |
|---------|------|-------------|
| `FAST` | fan-in/fan-out, neighbourhood facts, risk triage | per-event streaming path (~2–4 ms) |
| `STANDARD` | + cycles, temporal motifs, risk propagation, evidence bundle | normal investigation |
| `DEEP` | + communities, centrality, multi-hop tracing, larger subgraph | deep network investigation |

Every run carries a **budget** (wall-clock + visit limits); if exhausted the
response is marked `analysis_metadata.budget.exhausted = true` and
`analysis_status = "completed_partial"` — never a hang, never a silent miss.

---

## 5. Example requests and actual responses

Full, un-truncated captures live in [`docs/example_responses/`](docs/example_responses/)
(reproduced with `scripts\capture_examples.py` against a live server).

### 5.1 Ingest transactions

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/graph/transaction `
  -ContentType 'application/json' -Body (@{
    events = @(
      @{ event_id='EVT-1'; transaction_id='TX-1'; source_account='ACC-8100'
         destination_account='ACC-9001'; amount=12000; timestamp=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
    )
  } | ConvertTo-Json)
```

Actual response (44-event batch):

```json
{"status": "accepted", "processed": 44, "accepted": 44, "duplicates": 0,
 "results": [{"event_id": "EVT-DEMO-1", "transaction_id": "TX-DEMO-1",
              "accepted": true, "action": "created", "graph_version": 1}],
 "graph_version": 44}
```

### 5.2 Analyse an account

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/graph/analyze `
  -ContentType 'application/json' `
  -Body '{"account_id":"ACC-9001","time_window":"5m","profile":"STANDARD"}'
```

Actual response (trimmed to structure — see the file for full output):

```json
{
  "analysis_id": "GRAPH-8F3A21C9",
  "analysis_status": "completed",
  "target_account": "ACC-9001",
  "time_window": "5m",
  "profile": "STANDARD",
  "graph_summary": {
    "nodes": 16, "edges": 15,
    "incoming_transactions": 7, "outgoing_transactions": 6,
    "non_settled_transactions": 2,
    "incoming_amount": 99750.0, "outgoing_amount": 85500.0
  },
  "detected_patterns": [
    {
      "pattern_type": "FAN_IN",
      "pattern_id": "FAN_IN:3f69c2e590",
      "accounts_involved": ["ACC-9001", "ACC-8100", "...", "ACC-8106"],
      "transaction_ids": ["TX-DEMO-1", "...", "TX-DEMO-7"],
      "amounts": [12000.0, 12750.0, 13500.0, 14250.0, 15000.0, 15750.0, 16500.0],
      "time_window": {"start": 1794630645.55, "end": 1794630945.55, "duration_seconds": 300.0},
      "algorithm": "fan_detection.detect_fan_in",
      "supporting_metrics": {
        "unique_accounts": 7, "transaction_count": 7, "total_amount": 99750.0,
        "time_concentration": {"span_seconds": 24.0, "peak_bucket_count": 7, "peak_share": 1.0},
        "amount_distribution": {"min": 12000.0, "max": 16500.0, "mean": 14250.0, "stdev": 1500.0}
      },
      "detection_parameters": {"min_unique_accounts": 5, "min_transactions": 5},
      "severity": "CRITICAL",
      "explanation": "Multiple accounts transferred funds into a common account. 7 unique counterparties, 7 settled transactions totalling 99750.0 in the analysed window."
    },
    { "pattern_type": "CIRCULAR_TRANSACTION", "...": "..." },
    { "pattern_type": "FAN_IN_THEN_FAN_OUT", "...": "..." },
    { "pattern_type": "SEQUENTIAL_CHAIN", "...": "..." }
  ],
  "money_flow_paths": [],
  "communities": [],
  "centrality_metrics": {},
  "connected_accounts": [{"account_id": "ACC-8100", "directions": ["IN"], "transactions": 1, "total_amount": 12000.0, "...": "..."}],
  "graph_evidence": [
    {"evidence_id": "EV-ACC-9001-001", "kind": "GRAPH_FACT", "label": "ACCOUNT_ACTIVITY",
     "explanation": "Observed 7 incoming and 6 outgoing settled transactions for ACC-9001 in the selected window."},
    {"kind": "DETECTED_PATTERN", "label": "FAN_IN", "...": "..."},
    {"kind": "RISK_INTERPRETATION", "label": "GRAPH_RISK_SCORE", "...": "..."}
  ],
  "risk_assessment": {
    "score": 0.4748, "severity": "HIGH",
    "signals": [
      {"signal": "fan_in", "value": 0.76, "weight": 0.22, "contribution": 0.1672},
      {"signal": "fan_out", "value": 0.58, "weight": 0.22, "contribution": 0.1276},
      {"signal": "temporal_motifs", "value": 1.0, "weight": 0.14, "contribution": 0.14}
    ],
    "explanations": ["Fan-in detected: 7 unique sources, 7 settled transactions.", "..."],
    "disclaimer": "Rule-based graph triage score ... not a legal or behavioural verdict ..."
  },
  "analysis_metadata": {
    "algorithms_executed": ["cycle_detection.find_cycles", "fan_detection.detect_fan_in",
      "fan_detection.detect_fan_out", "graph_store.neighborhood", "risk_engine.assess",
      "subgraph_extractor.extract_subgraph", "temporal_motifs.detect_temporal_motifs"],
    "execution_time_ms": 10.42,
    "graph_version": 44,
    "budget": {"visits": 522, "exhausted": false, "remaining_ms": 1989.6},
    "evidence_digest": "8129af1bcafa"
  }
}
```

### 5.3 Money-flow trace

`GET /api/v1/graph/trace/ACC-6001/ACC-6004?max_hops=4&window=5m`

```json
{
  "source": "ACC-6001", "destination": "ACC-6004", "path_count": 1,
  "shortest_hops": 3, "truncated": false,
  "paths": [{
    "hop_count": 3,
    "accounts": ["ACC-6001", "ACC-6002", "ACC-6003", "ACC-6004"],
    "transaction_ids": ["TX-DEMO-20", "TX-DEMO-21", "TX-DEMO-22"],
    "total_amount": 264000.0, "min_hop_amount": 86000.0,
    "duration_seconds": 8.0, "chronologically_ordered": true,
    "hops": [
      {"position": 1, "from_account": "ACC-6001", "to_account": "ACC-6002",
       "transaction_id": "TX-DEMO-20", "timestamp": 1794630925.11,
       "amount": 90000.0, "status": "COMPLETED"},
      {"position": 2, "...": "..."},
      {"position": 3, "...": "..."}
    ]
  }]
}
```

### 5.4 Cycles

`GET /api/v1/graph/cycles?window=5m`

```json
{
  "cycle_count": 2,
  "cycles": [{
    "accounts": ["ACC-7001", "ACC-7002", "ACC-7003"],
    "transaction_ids": ["TX-DEMO-14", "TX-DEMO-15", "TX-DEMO-16"],
    "amounts": [50000.0, 50000.0, 50000.0],
    "timestamps": [1794630865.11, 1794630868.11, 1794630871.11],
    "length": 3, "total_amount": 150000.0, "duration_seconds": 6.0
  }],
  "repeated_activity": [{
    "accounts": ["ACC-7001", "ACC-7002", "ACC-7003"],
    "occurrences": 2,
    "transaction_ids": ["TX-DEMO-14", "...", "TX-DEMO-19"],
    "total_amount": 300000.0, "edges_per_hop": [2, 2, 2]
  }]
}
```

### 5.5 Communities, metrics, health

```json
// GET /api/v1/graph/communities?window=5m
{"community_count": 3, "algorithm": "louvain",
 "communities": [{"community_id": "COMM-001", "size": 14, "connectivity": 0.1429,
                  "internal_volume": 185250.0, "suspicious_concentration": false}]}

// GET /api/v1/graph/metrics?window=5m
{"accounts_measured": 61,
 "bridge_nodes": ["ACC-6002", "ACC-6003", "ACC-9001"],
 "top_pagerank": [{"account_id": "ACC-9001", "pagerank": 0.0623505}]}

// GET /api/v1/graph/health
{"status": "healthy", "graph_version": 44, "nodes": 63, "edges": 44,
 "cache_status": {"communities": {"1794630645:1794630945": 0.4},
                  "centrality": {"1794630645:1794630945": 0.0}}}
```

---

## 6. Evidence & explainability model

Every analysis separates three evidence kinds so a consumer can weight them
differently:

| `kind` | Meaning | Producer |
|--------|---------|----------|
| `GRAPH_FACT` | Directly observed counts/amounts — never inferred | graph store |
| `DETECTED_PATTERN` | Output of a named algorithm with parameters + metrics | algorithms |
| `RISK_INTERPRETATION` | Rule-based scoring judgement (with disclaimer) | risk engine |

Guarantees:

* **No fabricated evidence** — every referenced `transaction_id` exists in the
  store (asserted by `test_evidence_references_real_transactions`).
* Every pattern carries: `pattern_type`, deterministic `pattern_id`,
  `accounts_involved`, `transaction_ids`, `amounts`, `timestamps`,
  `time_window`, `algorithm`, `supporting_metrics`, `detection_parameters`,
  `severity`, `explanation`.
* Direct facts, detected patterns and risk interpretations are separate arrays
  inside `graph_evidence` — never blended.
* `analysis_metadata.evidence_digest` lets consumers cache/deduplicate.

---

## 7. How another AI application consumes this engine

1. **Ask for analysis** — `POST /api/v1/graph/analyze` with the account and a
   time window. Use `FAST` inside a streaming loop, `STANDARD` for interactive
   investigation, `DEEP` for offline network analysis.
2. **Read the structure, not the graph** — the response is self-contained:
   patterns already include transaction ids, amounts, timestamps, metrics and
   human-readable explanations. Your AI layer never touches NetworkX or the
   store.
3. **Ground responses in evidence** — when your LLM writes a report, quote
   `detected_patterns[].explanation` + `transaction_ids`; when challenged,
   `GET /api/v1/graph/account/{id}/transactions` returns the underlying
   records (`page`/`page_size`), so every claim is auditable back to source
   events.
4. **Separate fact from judgement** — feed `graph_evidence` filtered by `kind`
   into prompts: use `GRAPH_FACT` as trusted context, `DETECTED_PATTERN` as
   findings, and `RISK_INTERPRETATION` as a triage hint (never as a verdict).
5. **Prioritise work** — `risk_assessment.score/severity` +
   `analysis_metadata.execution_time_ms` let a orchestrator decide which
   accounts deserve `DEEP` analysis.
6. **Stream results** — wire `GraphEventProcessor(sink=your_publisher)` to push
   `FAST` evidence payloads (Kafka/Redis/webhook — any callable) as
   transactions arrive; the sink contract is
   `payload = {"event_id", "transaction_id", "graph_version", "processing_latency_ms", "analysis": {...}}`.
7. **Stay deterministic** — window presets, pattern ids and seeded Louvain make
   repeated requests reproducible; `graph_version` tells you when state moved.

Minimal client example (Python):

```python
import httpx

r = httpx.post("http://127.0.0.1:8000/api/v1/graph/analyze",
               json={"account_id": "ACC-9001", "time_window": "5m", "profile": "STANDARD"},
               timeout=10).json()

for pattern in r["detected_patterns"]:
    print(pattern["severity"], pattern["pattern_type"], pattern["explanation"])
    # ground the claim: pattern["transaction_ids"] are real, auditable transactions
```

---

## 8. Streaming integration

```
EventSource (poll) ──> GraphEventProcessor ──> sink(payload)
   │                      1. validate (pydantic)
   │                      2. dedupe (event id + state)
   │                      3. incremental graph update
   │                      4. temporal index + sliding counters
   │                      5. FAST analysis
   │                      6. structured evidence
   └─ SyntheticEventSource / ListEventSource / KafkaEventSource (optional)
```

The graph logic never imports a broker: `scripts\run_simulator.py` runs the
exact same pipeline locally, and `KafkaEventSource` is opt-in
(`pip install kafka-python`). Late/out-of-order events are indexed by
transaction timestamp; duplicates are rejected before any state changes.

---

## 9. Storage

| Layer | Implementation | Required? |
|-------|----------------|-----------|
| Graph computation | NetworkX `MultiDiGraph` | ✅ yes (initial) |
| Fast lookup | in-memory adjacency + time indexes | ✅ yes (initial) |
| Durable events | `TransactionRepository` (memory / JSONL file) | pluggable |
| Hot state/cache | Redis (via repository/cache adapter) | optional |
| Historical graph | Neo4j (export adapter) | optional |
| Durable SQL | PostgreSQL (via repository adapter) | optional |

`GraphPersistenceService.rebuild()` restores the entire graph from durable
events (tested: `test_rebuild_from_durable_events`).

---

## 10. Performance — measured, not fabricated

`scripts\benchmark.py` on this machine (Windows, Python 3.13, single process):

| Target | Effective throughput | ingest p50 | ingest p95 | ingest p99 | analysis p50/p95 (FAST) | tracemalloc peak |
|--------|---------------------|-----------|-----------|-----------|--------------------------|------------------|
| 50 TPS | 49.99 tx/s (400 events) | 2.65 ms | 4.36 ms | 5.51 ms | 2.32 / 3.97 ms | 10.4 MB |
| 100 TPS | 100.0 tx/s (800 events) | 2.59 ms | 4.52 ms | 6.79 ms | 2.37 / 4.58 ms | 18.3 MB |
| 500 TPS (stress) | 352 tx/s sustained (3000 events) | 2.26 ms | 4.07 ms | 5.34 ms | 2.71 / 6.72 ms | 32.1 MB |

Notes (honest limitations):

* Single-threaded ingest caps sustained throughput at ~400–450 tx/s on this
  hardware; the 500 TPS run shows the engine degrading gracefully (it never
  drops events — it saturates). Scale by running multiple worker processes.
* Analysis runs inline in the ingest loop for the benchmark; in production the
  `FAST` path is the same ~2–4 ms cost, and `DEEP` work (communities,
  centrality) runs in a background thread with TTL caches.
* Re-run locally with the commands in §3 — numbers change with hardware.

Performance engineering applied: incremental writes only, `bisect` window
queries, bounded BFS/DFS with visit budgets, canonical-start cycle DFS (no
duplicates), sampled betweenness, degree caps, TTL caches with background
refresh, O(1) sliding-window counters, no full-graph copies in request paths.

---

## 11. Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

**107 tests** covering: normal transactions, fan-in/fan-out (positive +
negative), circular flows (length bounds, dedupe, repeats, non-settled loops),
multi-hop (hop limits, min-amount, chronological order, shortest-only),
temporal windows, duplicates, late/out-of-order events, reversed/held/rejected
statuses, shared destinations, large neighbourhood truncation, motifs, community
determinism, centrality, bounded risk propagation, streaming processor,
API integration (all endpoints + structured errors), evidence authenticity, and
measured performance under load.

Deterministic synthetic data: `SyntheticTransactionGenerator(seed=...)`
produces reproducible normal + attack scenarios (fan-in, fan-out, cycles,
chains, duplicates, late events, status changes).

---

## 12. Configuration (environment variables)

| Variable | Default | Meaning |
|----------|---------|---------|
| `MULEGRAPH_MAX_NODES` / `_MAX_EDGES` / `_MAX_DEGREE` | 200k / 2M / 5k | structural limits |
| `MULEGRAPH_MAX_HOPS` | 6 | traversal depth cap |
| `MULEGRAPH_ANALYSIS_TIMEOUT_MS` | 2000 | FAST/STANDARD budget |
| `MULEGRAPH_DEEP_TIMEOUT_MS` | 10000 | DEEP budget |
| `MULEGRAPH_FAN_MIN_UNIQUE` / `_FAN_MIN_TX` | 5 / 5 | fan thresholds |
| `MULEGRAPH_PROPAGATION_DEPTH` / `_DECAY` | 2 / 0.5 | risk propagation |
| `MULEGRAPH_COMMUNITY_REFRESH_S` / `MULEGRAPH_CENTRALITY_REFRESH_S` | 30 / 30 | cache TTLs |
| `MULEGRAPH_BACKGROUND_ANALYSIS` | 1 | background refresh toggle |
| `MULEGRAPH_DEFAULT_WINDOW` / `MULEGRAPH_DEFAULT_PROFILE` | 5m / STANDARD | API defaults |
| `MULEGRAPH_EVENT_FILE` | – | JSONL durable event log path |

---

## 13. Design principles

* **Correctness first** — settled-only money semantics, evidence preservation,
  deterministic outputs, positive *and* negative tests per algorithm.
* **Explainability** — every number in a response can be traced to named
  parameters, an algorithm and real transaction ids.
* **Bounded everything** — hops, paths, cycles, visits, wall-clock, degrees,
  page sizes; no unbounded traversal anywhere.
* **No unnecessary dependencies** — 5 runtime packages, pure-Python PageRank
  fallback (no scipy required), optional integrations stay optional.
* **AI-provider independent** — the engine emits structured JSON; intelligence
  about *what the graph means for a case* belongs to the consuming system.
