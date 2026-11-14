import { config } from "../config.js";

export class GraphEngineError extends Error {
  constructor(
    message: string,
    public readonly code: "GRAPH_ENGINE_TIMEOUT" | "GRAPH_ENGINE_UNAVAILABLE",
  ) {
    super(message);
    this.name = "GraphEngineError";
  }
}

export type RiskEvaluationRequest = {
  transactionId: string;
  senderId: string;
  receiverId: string;
  amountPaise: number;
  currency: "INR";
  eventTimestamp: string;
};

export async function evaluateRisk(request: RiskEvaluationRequest): Promise<Record<string, unknown>> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2_000);

  try {
    const response = await fetch(`${config.GRAPH_ENGINE_URL}/api/v1/graph/analyze`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(config.GRAPH_ENGINE_API_KEY ? { authorization: `Bearer ${config.GRAPH_ENGINE_API_KEY}` } : {}),
      },
      body: JSON.stringify({
        account_id: request.senderId,
        time_window: "5m",
        profile: "STANDARD",
        include_subgraph: false,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new GraphEngineError(`Graph engine returned ${response.status}`, "GRAPH_ENGINE_UNAVAILABLE");
    }
    return (await response.json()) as Record<string, unknown>;
  } catch (error) {
    if (error instanceof GraphEngineError) throw error;
    if (error instanceof Error && error.name === "AbortError") {
      throw new GraphEngineError("Graph engine request timed out", "GRAPH_ENGINE_TIMEOUT");
    }
    throw new GraphEngineError("Graph engine is unavailable", "GRAPH_ENGINE_UNAVAILABLE");
  } finally {
    clearTimeout(timeout);
  }
}
