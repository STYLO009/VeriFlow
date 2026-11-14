
# Database and Data Storage Design

## 1. Storage Ownership

| Storage | Responsibility |
|---|---|
| PostgreSQL | Durable business records |
| Redis | Live graph indexes and event streams |

Node.js + Prisma exclusively owns PostgreSQL business-record persistence.

Python uses Redis for graph computation.

## 2. Core Models

### Account

- Account ID
- Unique account reference
- Account age
- Creation timestamp

### Transaction

- Transaction reference
- Sender
- Receiver
- Amount in paise
- Event timestamp
- Transaction status
- Original transaction reference for reversals

### RiskDecision

- Transaction reference
- Risk score
- Decision
- Evidence
- Model version
- Creation timestamp

### FraudSignal

- Pattern type
- Severity
- Involved accounts
- Evidence transaction IDs
- Feature values

### ProcessingEvent

- Event reference
- Transaction reference
- Event type
- Processing status
- Attempt count
- Error information

### AccountRiskHistory

- Account reference
- Risk score
- Model version
- Evidence
- Calculation timestamp

## 3. Prisma Schema Starter

```prisma
enum TransactionStatus {
  PENDING
  SUCCESS
  FAILED
  REVERSED
}

enum RiskDecisionType {
  ALLOW
  MONITOR
  REVIEW
  ESCALATE
}

model Account {
  id             String   @id @default(uuid())
  accountRef     String   @unique
  accountAgeDays Int?
  createdAt      DateTime @default(now())
  updatedAt      DateTime @updatedAt

  sentTransactions Transaction[] @relation("Sender")
  receivedTransactions Transaction[] @relation("Receiver")
}

model Transaction {
  id             String @id @default(uuid())
  transactionRef String @unique
  senderId       String
  receiverId     String
  amountPaise    BigInt
  eventTimestamp DateTime
  status         TransactionStatus
  originalTransactionRef String?
  createdAt      DateTime @default(now())
  updatedAt      DateTime @updatedAt

  sender Account @relation(
    "Sender",
    fields: [senderId],
    references: [id]
  )

  receiver Account @relation(
    "Receiver",
    fields: [receiverId],
    references: [id]
  )

  @@index([senderId, eventTimestamp])
  @@index([receiverId, eventTimestamp])
  @@index([status, eventTimestamp])
}

model RiskDecision {
  id             String @id @default(uuid())
  transactionRef String
  riskScore      Float
  decision       RiskDecisionType
  modelVersion   String
  evidence       Json
  createdAt      DateTime @default(now())

  @@index([transactionRef])
  @@index([createdAt])
}

model FraudSignal {
  id                     String @id @default(uuid())
  transactionRef         String?
  patternType            String
  severity               String
  involvedAccountIds     Json
  evidenceTransactionIds Json
  features               Json
  createdAt              DateTime @default(now())

  @@index([patternType])
  @@index([createdAt])
}

model ProcessingEvent {
  id             String @id @default(uuid())
  eventRef       String @unique
  transactionRef String
  eventType      String
  status         String
  attemptCount   Int @default(0)
  errorMessage   String?
  createdAt      DateTime @default(now())
  processedAt    DateTime?

  @@index([transactionRef])
  @@index([status, createdAt])
}

model AccountRiskHistory {
  id           String @id @default(uuid())
  accountRef   String
  riskScore    Float
  modelVersion String
  evidence     Json
  calculatedAt DateTime @default(now())

  @@index([accountRef, calculatedAt])
}
```

This is a starter schema. Review reversal constraints, audit requirements and relation semantics before production use.

## 4. Important Database Rules

- Use BigInt paise for monetary values.
- Never use floating-point values for money.
- Keep event time and insertion time separate.
- Use unique transaction references.
- Link reversals to original transactions.
- Preserve historical risk decisions.
- Index sender and receiver time-based queries.
- Paginate large transaction lists.
- Version evidence structures.

## 5. Redis Key Design

```text
graph:{account_id}:out
graph:{account_id}:in
account:{account_id}:metadata
txn:{transaction_id}
processed:{transaction_id}
risk:{account_id}
```

Recommended structures:

- Sorted Sets for adjacency indexes.
- Hashes or JSON for metadata.
- Explicit retention policies.
- Idempotency markers.
- Atomic sender and receiver updates.

Prefer storing transaction IDs in sorted sets and the transaction payload separately.

## 6. Consistency

Redis and PostgreSQL do not share a single atomic transaction.

Implement:

- Idempotent event processing
- Retry mechanisms
- Dead-letter streams
- Pending-message recovery
- Reconciliation jobs
- Reversal compensation
- Durable processing status
