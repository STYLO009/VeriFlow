import cors from "cors";
import express, { type Express } from "express";
import helmet from "helmet";
import rateLimit from "express-rate-limit";
import { config } from "./config.js";
import { GraphEngineClient } from "./graph-engine.js";
import { errorHandler, requestId } from "./middleware.js";
import { OutcomePublisher } from "./redis.js";
import { createApiRouter } from "./routes.js";
import { createAuthRouter, requireAuth } from "./auth.js";

export function createApp(): Express {
  const app = express();
  app.use(helmet());
  app.use(cors({ origin: config.FRONTEND_URL }));
  app.use(express.json({ limit: "1mb" }));
  app.use(requestId);
  app.use(rateLimit({ windowMs: 60_000, limit: 300, standardHeaders: "draft-7", legacyHeaders: false }));

  const apiRouter = createApiRouter(new GraphEngineClient(config), new OutcomePublisher(config));
  app.use("/api/v1/auth", createAuthRouter());
  app.get("/api/v1/health", (_request, response) => {
    response.json({ status: "healthy", service: "hackmatrix-ingestion-api" });
  });
  app.use("/api/v1", requireAuth, apiRouter);

  app.use(errorHandler);
  return app;
}
