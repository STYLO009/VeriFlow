
# Development Guide

## 1. Prerequisites

Install:

- Node.js LTS
- npm
- Python 3.11+
- PostgreSQL
- Redis
- Git

## 2. Repository Setup

```bash
git clone <repository-url>
cd muleshield
```

Create `.env` from `.env.example`.

Never commit real credentials.

## 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Suggested dependencies:

```bash
npm install react-router-dom
npm install @xyflow/react
npm install axios
npm install @tanstack/react-query
npm install lucide-react
```

Use Tailwind CSS and shadcn/ui for the interface.

Recommended structure:

```text
frontend/src/
├── components/
│   ├── layout/
│   ├── dashboard/
│   ├── transactions/
│   ├── accounts/
│   ├── graph/
│   ├── alerts/
│   └── ui/
├── pages/
├── hooks/
├── services/
├── context/
├── types/
├── utils/
├── App.tsx
└── main.tsx
```

## 4. Node.js Backend Setup

```bash
cd backend
npm install
npm run dev
```

Suggested dependencies:

```bash
npm install express cors helmet dotenv zod
npm install @prisma/client redis
npm install jsonwebtoken bcryptjs
npm install -D typescript tsx prisma
npm install -D @types/node @types/express @types/cors
```

Generate Prisma client:

```bash
npx prisma generate
```

Run migrations:

```bash
npx prisma migrate dev --name init
```

## 5. Python Graph Engine Setup

### Windows PowerShell

```powershell
cd graph-engine

python -m venv .venv

.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Linux/macOS

```bash
cd graph-engine

python3 -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Suggested requirements:

```text
fastapi
uvicorn[standard]
redis
pydantic
pydantic-settings
python-dotenv
pytest
httpx
```

## 6. Environment Variables

Example `.env.example`:

```env
NODE_ENV=development

FRONTEND_URL=http://localhost:5173
BACKEND_PORT=4000

DATABASE_URL=postgresql://postgres:password@localhost:5432/muleshield

REDIS_URL=redis://localhost:6379/0

REDIS_STREAM_NAME=transaction-outcomes
REDIS_DEAD_LETTER_STREAM=transaction-outcomes:dead-letter
REDIS_CONSUMER_GROUP=graph-workers
REDIS_CONSUMER_NAME=backend-local
REDIS_MAX_ATTEMPTS=5
REDIS_RETRY_BASE_DELAY_MS=1000

GRAPH_ENGINE_URL=http://localhost:8000
GRAPH_ENGINE_API_KEY=replace-with-local-secret

GRAPH_TIME_WINDOW_SECONDS=300
GRAPH_MAX_DEPTH=4
GRAPH_MAX_NODES=500
GRAPH_MAX_EDGES=1500

RISK_MODEL_VERSION=rules-v1
```

Validate environment variables when each service starts.

The local development setup uses the existing external PostgreSQL URL from
`apps/Backend/.env`; PostgreSQL is not started by Docker Compose. Redis is the
only stateful infrastructure service started locally by Docker.

## 7. Suggested Root Package Configuration

```json
{
  "name": "muleshield",
  "private": true,
  "workspaces": [
    "frontend",
    "backend"
  ],
  "scripts": {
    "dev:frontend": "npm run dev --workspace=frontend",
    "dev:backend": "npm run dev --workspace=backend",
    "build:frontend": "npm run build --workspace=frontend",
    "build:backend": "npm run build --workspace=backend"
  }
}
```

Python runs independently.

## 8. Implementation Roadmap

### Phase 1: Infrastructure

- Create monorepo
- Configure PostgreSQL
- Configure Prisma
- Configure Redis
- Create FastAPI service
- Create Express service

### Phase 2: Graph Engine

- Redis adjacency storage
- Graph snapshot creation
- Temporal filtering
- BFS
- DFS
- Cycle detection

### Phase 3: Fraud Detection

- Fan-out
- Fan-in
- Pass-through
- Multi-hop
- Shared feature extraction
- Risk scoring
- Explainable evidence

### Phase 4: Backend Integration

- Transaction API
- Python service integration
- Risk decision persistence
- Redis Stream publisher
- Outcome processing
- Idempotency and retries

### Phase 5: Frontend

- Dashboard
- Transaction table
- Account details
- Graph explorer
- Risk alerts
- Evidence visualization

### Phase 6: Testing

- Normal transactions
- Suspicious transactions
- Duplicate events
- Failed transactions
- Reversals
- Out-of-order events
- Concurrent transactions
- High-degree accounts

## 9. Synthetic Data

Create datasets for:

- Normal peer-to-peer transfers
- Merchant-like high fan-in
- Merchant-like high fan-out
- Rapid layering
- Circular flows
- Repeated transfers
- Failed and reversed transactions
- Out-of-order events

Keep simulator ground-truth labels separate from detector outputs.

## 10. Performance Testing

Initial target: p95 risk evaluation below 100 ms under a documented workload.

Measure:

- p50 latency
- p95 latency
- p99 latency
- Throughput
- Error rate
- Redis lookup latency
- Traversal latency
- Feature extraction latency
- Detection latency
- Redis Stream consumer lag

Do not claim the target has been achieved until measured.

## 11. Security

- Use synthetic account identifiers for demonstrations.
- Never collect UPI PINs.
- Avoid logging unnecessary financial data.
- Restrict Redis and PostgreSQL access.
- Protect internal Python APIs.
- Apply validation and rate limits.
- Use role-based access control.
- Maintain audit logs.
- Define retention policies.
