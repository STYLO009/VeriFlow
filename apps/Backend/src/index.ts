import "dotenv/config";
import { createApp } from "./app.js";
import { config } from "./config.js";
import { prisma } from "./prisma.js";
import { OutcomeConsumer } from "./redis-consumer.js";

const app = createApp();
const consumer = new OutcomeConsumer();
const server = app.listen(config.PORT, () => {
  console.log(`Hackmatrix backend listening on http://localhost:${config.PORT}`);
});

async function shutdown(signal: string): Promise<void> {
  console.log(`Received ${signal}; shutting down`);
  server.close(async () => {
    await prisma.$disconnect();
    await consumer.stop().catch(() => undefined);
    process.exit(0);
  });
}

process.on("SIGINT", () => void shutdown("SIGINT"));
process.on("SIGTERM", () => void shutdown("SIGTERM"));

void consumer.start().catch((error) => {
  console.warn("Redis outcome consumer unavailable at startup", error);
});
