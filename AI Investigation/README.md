# MuleGraph AI Investigator

This folder runs the AI investigation API as a separate service from the
MuleGraph graph engine. The investigator is read-only: it retrieves evidence
through the graph engine's REST API and never imports graph data or mutates
graph state itself.

## Run locally

1. Create a virtual environment and install this folder's dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env`, set at least one provider key, and point
   `MULEGRAPH_AI_GRAPH_API_URL` at the running graph engine (for example,
   `http://127.0.0.1:8000`).

3. Start the service from this folder:

   ```powershell
   uvicorn app.main:app --host 0.0.0.0 --port 8001
   ```

The AI endpoints are available under `/api/v1/ai`; interactive API docs are at
`/docs`. The graph engine remains a separate process, usually on port 8000.

Provider keys belong in environment variables or the ignored local `.env`
file. Never commit real keys.
