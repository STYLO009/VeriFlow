import { z } from "zod";

const envSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  PORT: z.coerce.number().int().positive().default(4000),
  FRONTEND_URL: z.string().url().default("http://localhost:5173"),
  DATABASE_URL: z.string().min(1),
  REDIS_URL: z.string().url().default("redis://localhost:6379/0"),
  GRAPH_ENGINE_URL: z.string().url().default("http://localhost:8000"),
  GRAPH_ENGINE_TIMEOUT_MS: z.coerce.number().int().positive().default(2_000),
  GRAPH_ENGINE_API_KEY: z.string().optional(),
  JWT_SECRET: z.string().min(16).default("development-only-change-me-please"),
  JWT_EXPIRES_IN: z.string().default("7d"),
  BCRYPT_SALT_ROUNDS: z.coerce.number().int().min(4).max(15).default(10),
  OUTCOME_API_KEY: z.string().min(16).optional(),
  GEMINI_API_KEY: z.string().min(20).optional(),
  GEMINI_MODEL: z.string().min(1).default("gemini-2.5-flash"),
  REDIS_STREAM_NAME: z.string().min(1).default("transaction-outcomes"),
  REDIS_DEAD_LETTER_STREAM: z.string().min(1).default("transaction-outcomes:dead-letter"),
  REDIS_CONSUMER_GROUP: z.string().min(1).default("graph-workers"),
  REDIS_CONSUMER_NAME: z.string().min(1).default(`backend-${process.pid}`),
  REDIS_MAX_ATTEMPTS: z.coerce.number().int().positive().default(5),
  REDIS_RETRY_BASE_DELAY_MS: z.coerce.number().int().positive().default(1000),
});

export const config = envSchema.parse(process.env);
export type AppConfig = typeof config;
