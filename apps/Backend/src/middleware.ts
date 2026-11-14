import { randomUUID } from "node:crypto";
import type { ErrorRequestHandler, RequestHandler } from "express";
import { ZodError } from "zod";
import { AppError } from "./errors.js";
import { config } from "./config.js";

export const requestId: RequestHandler = (req, res, next) => {
  const id = req.header("x-request-id")?.trim() || randomUUID();
  res.setHeader("x-request-id", id);
  res.locals.requestId = id;
  next();
};

export const errorHandler: ErrorRequestHandler = (error, req, res, _next) => {
  const requestIdValue = res.locals.requestId as string;
  if (error instanceof AppError) {
    res.status(error.statusCode).json({
      error: { code: error.code, message: error.message, requestId: requestIdValue, detail: error.detail },
    });
    return;
  }

  if (error instanceof ZodError) {
    res.status(422).json({
      error: {
        code: "VALIDATION_ERROR",
        message: "Request validation failed.",
        requestId: requestIdValue,
        detail: error.flatten(),
      },
    });
    return;
  }

  if (error instanceof SyntaxError && "body" in error) {
    res.status(400).json({
      error: {
        code: "VALIDATION_ERROR",
        message: "Request body contains invalid JSON.",
        requestId: requestIdValue,
      },
    });
    return;
  }

  console.error("Unhandled request error", { requestId: requestIdValue, method: req.method, path: req.path, error });
  res.status(500).json({
    error: { code: "INTERNAL_ERROR", message: "Unexpected server error.", requestId: requestIdValue },
  });
};

export const trustedOutcomeSource: RequestHandler = (req, _res, next) => {
  if (!config.OUTCOME_API_KEY) {
    next();
    return;
  }
  if (req.header("x-outcome-api-key") !== config.OUTCOME_API_KEY) {
    next(new AppError("UNAUTHORIZED", 401, "Trusted payment-event credentials are required."));
    return;
  }
  next();
};
