import { AppConfig } from "./config.js";
import { AppError } from "./errors.js";

export type TransactionEvaluationRequest = {
  transactionId: string;
  senderId: string;
  receiverId: string;
  amountPaise: number;
  currency: string;
  eventTimestamp: string;
};

export type Pattern = {
  name: string;
  detected?: boolean;
  severity: string;
  features?: Record<string, unknown>;
  accountIds?: string[];
  transactionIds?: string[];
};

export type EvaluationResponse = {
  transactionId: string;
  riskScore: number;
  decision: "ALLOW" | "MONITOR" | "REVIEW" | "ESCALATE";
  processingStatus: "COMPLETE" | "INCOMPLETE_EVIDENCE";
  patterns: Pattern[];
  evidence: Record<string, unknown>;
  modelVersion: string;
};

export class GraphEngineClient {
  constructor(private readonly config: AppConfig) {}

  async evaluate(request: TransactionEvaluationRequest, requestId: string): Promise<EvaluationResponse> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.config.GRAPH_ENGINE_TIMEOUT_MS);
    try {
      // Keep Python's temporal graph in sync before asking it for a decision.
      // This makes newly submitted transactions visible to the same analysis
      // path used by the seeded PaySim data.
      const ingest = await fetch(`${this.config.GRAPH_ENGINE_URL}/api/v1/graph/transaction`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-request-id": requestId,
          ...(this.config.GRAPH_ENGINE_API_KEY
            ? { authorization: `Bearer ${this.config.GRAPH_ENGINE_API_KEY}` }
            : {}),
        },
        body: JSON.stringify({
          event: {
            event_id: `node-${request.transactionId}`,
            transaction_id: request.transactionId,
            source_account: request.senderId,
            destination_account: request.receiverId,
            amount: request.amountPaise / 100,
            currency: request.currency,
            timestamp: request.eventTimestamp,
            status: "COMPLETED",
            event_type: "TRANSACTION",
            metadata: { source: "node-api" },
          },
        }),
        signal: controller.signal,
      });
      if (!ingest.ok) {
        throw new AppError("GRAPH_ENGINE_ERROR", 502, "Risk graph ingestion failed.", await ingest.text());
      }

      const response = await fetch(`${this.config.GRAPH_ENGINE_URL}/api/v1/graph/analyze`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-request-id": requestId,
          ...(this.config.GRAPH_ENGINE_API_KEY
            ? { authorization: `Bearer ${this.config.GRAPH_ENGINE_API_KEY}` }
            : {}),
        },
        body: JSON.stringify({
          account_id: request.receiverId,
          time_window: "5m",
          profile: "STANDARD",
          include_subgraph: false,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new AppError(
          response.status >= 500 ? "GRAPH_ENGINE_UNAVAILABLE" : "GRAPH_ENGINE_ERROR",
          response.status >= 500 ? 503 : 502,
          "Risk evaluation service returned an error.",
          await response.text(),
        );
      }

      const payload = (await response.json()) as {
        risk_assessment?: { score?: number; severity?: string };
        detected_patterns?: Array<Pattern & { pattern_type?: string; accounts_involved?: string[]; transaction_ids?: string[] }>;
        graph_evidence?: unknown;
        analysis_status?: string;
        analysis_metadata?: { model_version?: string };
      };
      const riskScore = Number(payload.risk_assessment?.score ?? 0) * 100;
      const severity = payload.risk_assessment?.severity ?? "LOW";
      const decision = severity === "CRITICAL" || riskScore >= 80
        ? "ESCALATE"
        : severity === "HIGH" || riskScore >= 60
          ? "REVIEW"
          : riskScore >= 30 ? "MONITOR" : "ALLOW";
      const patterns = (payload.detected_patterns ?? []).map((pattern) => ({
        name: pattern.name ?? pattern.pattern_type ?? "GRAPH_PATTERN",
        detected: pattern.detected ?? true,
        severity: pattern.severity,
        features: pattern.features,
        accountIds: pattern.accountIds ?? pattern.accounts_involved,
        transactionIds: pattern.transactionIds ?? pattern.transaction_ids,
      }));
      return {
        transactionId: request.transactionId,
        riskScore,
        decision,
        processingStatus: payload.analysis_status === "INCOMPLETE_EVIDENCE" ? "INCOMPLETE_EVIDENCE" : "COMPLETE",
        patterns,
        evidence: {
          graphEvidence: payload.graph_evidence ?? [],
          riskAssessment: payload.risk_assessment ?? {},
        },
        modelVersion: payload.analysis_metadata?.model_version ?? "mulegraph-rules-v1",
      };
    } catch (error) {
      if (error instanceof AppError) throw error;
      if (error instanceof Error && error.name === "AbortError") {
        throw new AppError("GRAPH_ENGINE_TIMEOUT", 504, "Risk evaluation timed out.", error);
      }
      throw new AppError("GRAPH_ENGINE_UNAVAILABLE", 503, "Risk evaluation is temporarily unavailable.", error);
    } finally {
      clearTimeout(timeout);
    }
  }

  async neighborhood(accountId: string, window: string, requestId: string): Promise<Record<string, unknown>> {
    const response = await this.request(
      `/api/v1/graph/account/${encodeURIComponent(accountId)}/neighborhood?hops=2&window=${encodeURIComponent(window)}`,
      { method: "GET", requestId },
    );
    return (await response.json()) as Record<string, unknown>;
  }

  private async request(path: string, options: { method: string; requestId: string }): Promise<Response> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.config.GRAPH_ENGINE_TIMEOUT_MS);
    try {
      const response = await fetch(`${this.config.GRAPH_ENGINE_URL}${path}`, {
        method: options.method,
        headers: {
          "x-request-id": options.requestId,
          ...(this.config.GRAPH_ENGINE_API_KEY ? { authorization: `Bearer ${this.config.GRAPH_ENGINE_API_KEY}` } : {}),
        },
        signal: controller.signal,
      });
      if (!response.ok) {
        const detail = await response.text();
        if (response.status === 404) {
          throw new AppError("NOT_FOUND", 404, "Graph resource was not found.", detail);
        }
        throw new AppError(
          response.status >= 500 ? "GRAPH_ENGINE_UNAVAILABLE" : "GRAPH_ENGINE_ERROR",
          response.status >= 500 ? 503 : 502,
          "Graph engine request failed.",
          detail,
        );
      }
      return response;
    } catch (error) {
      if (error instanceof AppError) throw error;
      if (error instanceof Error && error.name === "AbortError") {
        throw new AppError("GRAPH_ENGINE_TIMEOUT", 504, "Graph engine request timed out.", error);
      }
      throw new AppError("GRAPH_ENGINE_UNAVAILABLE", 503, "Graph engine is temporarily unavailable.", error);
    } finally {
      clearTimeout(timeout);
    }
  }
}
