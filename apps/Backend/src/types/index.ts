export type ApiErrorCode =
  | "VALIDATION_ERROR"
  | "NOT_FOUND"
  | "TRANSACTION_ALREADY_EXISTS"
  | "GRAPH_ENGINE_TIMEOUT"
  | "GRAPH_ENGINE_ERROR"
  | "GRAPH_ENGINE_UNAVAILABLE"
  | "REDIS_UNAVAILABLE"
  | "UNAUTHORIZED"
  | "INTERNAL_ERROR";

export type ApiErrorBody = {
  code: ApiErrorCode | string;
  message: string;
  requestId: string;
  detail?: unknown;
};

export type AuthenticatedRequest = Express.Request & {
  user?: { userId: string };
};

declare global {
  namespace Express {
    interface Request {
      user?: { userId: string; role: "SUPER_ADMIN" | "FRAUD_ANALYST" | "INVESTIGATOR" | "COMPLIANCE_OFFICER" | "AUDITOR_VIEWER" };
    }
  }
}
