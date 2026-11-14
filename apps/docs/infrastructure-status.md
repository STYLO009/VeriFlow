# Infrastructure Implementation Status

## Implemented

| Capability | Implementation |
|---|---|
| Redis container | `docker-compose.yml`, `redis:7-alpine` |
| Redis consumer group | `graph-workers` on `transaction-outcomes` |
| Message acknowledgement | `XACK` after successful processing |
| Pending-message recovery | `XAUTOCLAIM` |
| Retry/backoff | Bounded exponential backoff using environment configuration |
| Dead-letter handling | `transaction-outcomes:dead-letter` |
| Idempotency marker | `processed:{eventRef}` |
| PostgreSQL | Existing external database URL from `apps/Backend/.env` |

## Planned, not implemented

| Capability | Reason |
|---|---|
| Reconciliation jobs | Requires an explicit operational schedule and source-of-truth policy |
| Out-of-order event policy | Requires business-defined bounded-lateness rules |
| Full reversal compensation | Requires a finalized graph-edge compensation model |
| Distributed tracing | Requires a selected telemetry backend |
| Production secret rotation | Requires deployment-secret ownership and provider selection |

The planned items are intentionally documented as future work and are not
promised by the current runtime.
