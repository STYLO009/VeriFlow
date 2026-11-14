
# Graph Algorithms and Fraud Detection

## 1. Graph Representation

MuleShield models accounts as vertices and transactions as directed edges.

G(t) = (V, E)

Each edge:

`e = (sender, receiver, amount, timestamp, transaction_id)`

The graph is:

- Directed
- Weighted
- Temporal
- A multigraph

## 2. Bounded Graph Traversal

Initial configuration:

```python
GRAPH_CONFIG = {
    "time_window_seconds": 300,
    "max_depth": 4,
    "max_nodes": 500,
    "max_edges": 1500
}
```

These are initial tuning values, not production-validated limits.

The graph snapshot must enforce:

- Time-window filtering
- Maximum depth
- Maximum node count
- Maximum edge count
- Deterministic traversal
- Completeness tracking

## 3. Breadth-First Search

BFS explores neighboring accounts level by level.

Useful for:

- Nearby account discovery
- Multi-hop paths
- Bounded graph expansion

```python
from collections import deque

def bounded_bfs(start, get_neighbors, max_depth=4, max_nodes=500):
    queue = deque([(start, 0)])
    visited = {start}

    while queue and len(visited) < max_nodes:
        node, depth = queue.popleft()

        if depth >= max_depth:
            continue

        for edge in get_neighbors(node):
            neighbor = edge.target

            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

    return visited
```

Production implementation should additionally enforce edge budgets, event-time constraints and truncation status.

## 4. Depth-First Search

DFS explores a path deeply before backtracking.

Useful for:

- Cycle detection
- Path exploration
- Detecting circular transaction routes

Example:

`A → B → C → D → A`

A cycle alone is not evidence of fraud. Evaluate its timing, amount patterns, repetition and supporting signals.

## 5. Temporal Path Detection

A chronological path must satisfy:

`t1 <= t2 <= t3 <= ... <= tn`

The complete path must fit within the configured time window:

`t_last - t_first <= W`

Use event time for graph analysis and ingestion time for pipeline monitoring.

## 6. Fan-Out Detection

One account sends money to many unique recipients in a short interval.

Example:

```text
        B
       /
A ---- C
       \
        D
```

Features:

- Outgoing transaction count
- Unique receiver count
- Total outgoing volume
- Time interval
- Amount distribution

## 7. Fan-In Detection

Many accounts send money to one receiver.

Example:

```text
A ----\
B -----\
C ------> D
E -----/
```

Features:

- Incoming transaction count
- Unique sender count
- Total incoming volume
- Time interval
- Subsequent outgoing transfers

## 8. Pass-Through Detection

An account forwards incoming funds shortly after receiving them.

Example:

`A → B → C`

Example:

- A transfers ₹25,000 to B.
- B transfers ₹24,500 to C shortly afterward.

Approximate pass-through ratio:

`PTR = matched_outgoing_amount / incoming_amount`

FIFO matching can estimate relationships between incoming and outgoing amounts. It does not prove that the same money was transferred.

## 9. Cycle Detection

Example:

`A → B → C → A`

Evaluate:

- Cycle length
- Time to complete
- Amount similarity
- Repetition
- Chronological ordering

Canonicalize cycles to avoid counting rotations of the same cycle repeatedly.

## 10. Multi-Hop Detection

Example:

`A → B → C → D → E`

Features:

- Hop count
- Intermediary count
- Time elapsed
- Amount changes
- Risky neighbors
- Other detected patterns

Use bounded BFS rather than enumerating every possible path.

## 11. Shared Features

| Feature | Description |
|---|---|
| in_degree_5m | Unique incoming counterparties |
| out_degree_5m | Unique outgoing counterparties |
| incoming_txn_count | Incoming transaction count |
| outgoing_txn_count | Outgoing transaction count |
| incoming_amount_paise | Incoming transaction volume |
| outgoing_amount_paise | Outgoing transaction volume |
| transaction_velocity | Transaction frequency |
| pass_through_ratio | Estimated forwarding ratio |
| cycle_detected | Relevant cycle found |
| max_path_depth | Maximum relevant path depth |
| risky_neighbor_count | Previously flagged neighbors |

## 12. Risk Scoring

Initial weighted score:

`Risk = Σ(weight × normalized_signal) × 100`

Illustrative weights:

```python
WEIGHTS = {
    "fan_out": 0.20,
    "fan_in": 0.20,
    "pass_through": 0.25,
    "cycle": 0.15,
    "multi_hop": 0.20
}
```

Illustrative decision bands:

| Score | Decision |
|---|---|
| 0–29 | ALLOW |
| 30–59 | MONITOR |
| 60–79 | REVIEW |
| 80–100 | ESCALATE |

These values require calibration and validation. Correlated signals should not be blindly double-counted.

## 13. Evidence Generation

Every detected pattern should return:

- Pattern name
- Severity
- Supporting features
- Involved account IDs
- Supporting transaction IDs
- Observation window
- Scoring version

Example:

```json
{
  "pattern": "FAN_OUT",
  "detected": true,
  "severity": "HIGH",
  "features": {
    "uniqueReceivers": 12,
    "windowSeconds": 30
  },
  "accountIds": ["ACC-001"],
  "transactionIds": ["TXN-10", "TXN-11"]
}
```

Risk scores are analytical signals, not proof of criminal activity.
