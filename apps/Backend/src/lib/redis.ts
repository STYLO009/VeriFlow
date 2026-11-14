import { createClient, type RedisClientType } from "redis";
import { config } from "../config.js";

export const redis: RedisClientType = createClient({ url: config.REDIS_URL });

redis.on("error", (error) => {
  console.error("Redis client error", error);
});

export async function connectRedis(): Promise<void> {
  if (!redis.isOpen) await redis.connect();
}

export async function disconnectRedis(): Promise<void> {
  if (redis.isOpen) await redis.quit();
}
