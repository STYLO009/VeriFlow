import type { NextFunction, Request, Response } from "express";
import { ZodError } from "zod";
import { GraphEngineError } from "../lib/graph-engine.js";

export class HttpError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) {
    super(message);
    this.name = "HttpError";
  }
}

export function requestId(request: Request, response: Response, next: NextFunction): void {
  const id = request.header("x-request-id") ?? crypto.randomUUID();
  response.setHeader("x-request-id", id);
  next();
}

export function errorHandler(error: unknown, request: Request, response: Response, _next: NextFunction): void {
  const id = response.getHeader("x-request-id")?.toString() ?? "unknown";
  if (error instanceof ZodError) {
    response.status(400).json({ error: { code: "VALIDATION_ERROR", message: "Request validation failed", requestId: id, detail: error.flatten() } });
    return;
  }
  if (error instanceof GraphEngineError) {
    response.status(503).json({ error: { code: error.code, message: error.message, requestId: id } });
    return;
  }
  if (error instanceof HttpError) {
    response.status(error.status).json({ error: { code: error.code, message: error.message, requestId: id } });
    return;
  }
  console.error(`Unhandled error for ${request.method} ${request.path}`, error);
  response.status(500).json({ error: { code: "INTERNAL_ERROR", message: "Unexpected server error", requestId: id } });
}
