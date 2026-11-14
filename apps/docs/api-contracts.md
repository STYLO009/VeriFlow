
# API Contracts

## 1. Frontend to Node.js

Base URL:

`http://localhost:4000/api/v1`

| Method | Endpoint | Description |
|---|---|---|
| POST | /auth/login | User authentication |
| GET | /dashboard/overview | Dashboard statistics |
| GET | /transactions | Transaction listing |
| GET | /transactions/:id | Transaction details |
| POST | /transactions/evaluate | Risk evaluation |
| GET | /accounts | Account listing |
| GET | /accounts/:id | Account details |
| GET | /graph/:accountId | Account graph |
| GET | /risk/:transactionId | Risk details |
| GET | /alerts | Risk alerts |

## 2. Transaction Evaluation

`POST /api/v1/transactions/evaluate`

Request:

```json
{
  "transactionId": "TXN-1001",
  "senderId": "ACC-001",
  "receiverId": "ACC-002",
  "amountPaise": 2500000,
  "currency": "INR",
  "eventTimestamp": "2026-11-14T03:30:00.000Z"
}
```

Response:

```json
{
  "transactionId": "TXN-1001",
  "riskScore": 82.5,
  "decision": "ESCALATE",
  "processingStatus": "COMPLETE",
  "patterns": [
    {
      "name": "FAN_OUT",
      "severity": "HIGH"
    },
    {
      "name": "RAPID_PASS_THROUGH",
      "severity": "HIGH"
    }
  ],
  "evidence": {
    "uniqueReceivers": 12,
    "passThroughRatio": 0.94,
    "maxPathDepth": 3,
    "windowSeconds": 300
  },
  "modelVersion": "rules-v1"
}
```

## 3. Decision Types

- ALLOW
- MONITOR
- REVIEW
- ESCALATE

Processing statuses:

- COMPLETE
- INCOMPLETE_EVIDENCE

## 4. Python Internal API

Base URL:

`http://localhost:8000/internal/v1`

| Method | Endpoint | Description |
|---|---|---|
| POST | /evaluate | Evaluate proposed transaction |
| GET | /graph/{account_id} | Retrieve graph neighborhood |
| GET | /accounts/{account_id}/features | Account graph features |
| POST | /graph/outcomes | Apply transaction outcome |
| GET | /health | Health check |

The graph update endpoint is an alternative to Python consuming a dedicated Redis Stream. Choose one mechanism for the implementation.

## 5. Internal Evaluation Request

```json
{
  "transactionId": "TXN-1001",
  "senderId": "ACC-001",
  "receiverId": "ACC-002",
  "amountPaise": 2500000,
  "currency": "INR",
  "eventTimestamp": "2026-11-14T03:30:00.000Z"
}
```

## 6. Internal Evaluation Response

```json
{
  "transactionId": "TXN-1001",
  "riskScore": 82.5,
  "decision": "ESCALATE",
  "processingStatus": "COMPLETE",
  "patterns": [
    {
      "name": "FAN_OUT",
      "detected": true,
      "severity": "HIGH",
      "features": {
        "uniqueReceivers": 12,
        "windowSeconds": 30
      },
      "accountIds": ["ACC-001"],
      "transactionIds": ["TXN-10", "TXN-11"]
    }
  ],
  "evidence": {
    "maxPathDepth": 3,
    "passThroughRatio": 0.94
  },
  "modelVersion": "rules-v1"
}
```

## 7. Graph API Response

```json
{
  "accountId": "ACC-001",
  "windowSeconds": 300,
  "nodes": [
    {
      "id": "ACC-001",
      "riskScore": 82.5,
      "type": "account"
    },
    {
      "id": "ACC-002",
      "riskScore": 21.0,
      "type": "account"
    }
  ],
  "edges": [
    {
      "id": "TXN-1001",
      "source": "ACC-001",
      "target": "ACC-002",
      "amountPaise": 2500000,
      "eventTimestamp": "2026-11-14T03:30:00.000Z",
      "status": "SUCCESS"
    }
  ]
}
```

The frontend maps these nodes and edges to React Flow.

## 8. Error Format

```json
{
  "error": {
    "code": "GRAPH_ENGINE_UNAVAILABLE",
    "message": "Risk evaluation is temporarily unavailable.",
    "requestId": "req-123"
  }
}
```

Possible error codes:

- VALIDATION_ERROR
- TRANSACTION_ALREADY_EXISTS
- GRAPH_ENGINE_TIMEOUT
- GRAPH_ENGINE_UNAVAILABLE
- REDIS_UNAVAILABLE
- INCOMPLETE_EVIDENCE
- NOT_FOUND
- UNAUTHORIZED

## 9. API Requirements

- Validate requests at both service boundaries.
- Use integer paise.
- Use UTC timestamps consistently.
- Paginate list endpoints.
- Protect internal APIs with service authentication.
- Apply timeouts and rate limits.
- Include request IDs in logs.
- Never interpret graph-engine failure as zero risk.

The payment outcome endpoint must be restricted to a trusted payment-event source, not ordinary frontend users.

## 10. Authentication and roles

Authentication endpoints:

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/auth/me
```

The API uses bearer JWTs. The supported roles are:

| Role | Scope |
|---|---|
| `SUPER_ADMIN` | Full platform, user, role, configuration and audit access |
| `FRAUD_ANALYST` | Risk evaluation, alerts, transactions and outcome processing |
| `INVESTIGATOR` | Graph evidence, accounts, transactions and investigation cases |
| `COMPLIANCE_OFFICER` | Investigation cases, findings and audit records |
| `AUDITOR_VIEWER` | Read-only dashboards, transactions, risks and audit logs |

The first registered user is bootstrapped as `SUPER_ADMIN`.

## 11. Investigation and audit endpoints

```text
GET   /api/v1/cases
POST  /api/v1/cases
GET   /api/v1/cases/:id
PATCH /api/v1/cases/:id
GET   /api/v1/audit-logs
```

Case writes are limited to `SUPER_ADMIN`, `INVESTIGATOR`, and
`COMPLIANCE_OFFICER`. Audit-log reads are limited to `SUPER_ADMIN`,
`COMPLIANCE_OFFICER`, and `AUDITOR_VIEWER`.

## 12. Implemented stream reliability

The outcome stream uses a Redis consumer group and bounded failure handling:

- Stream: `transaction-outcomes`
- Consumer group: `graph-workers`
- Acknowledgement: `XACK` after successful processing
- Pending recovery: `XAUTOCLAIM`
- Retry count: `REDIS_MAX_ATTEMPTS`
- Backoff base: `REDIS_RETRY_BASE_DELAY_MS`
- Dead-letter stream: `transaction-outcomes:dead-letter`

Reconciliation jobs and out-of-order event policy are not implemented and are
explicitly future work.

