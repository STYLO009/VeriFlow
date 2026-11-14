import { createClient, type RedisClientType } from "redis";
import { AppConfig } from "./config.js";

export type OutcomeEvent = {
  eventRef: string;
  transactionRef: string;
  status: "SUCCESS" | "FAILED" | "REVERSED";
  occurredAt: string;
  originalTransactionRef?: string;
  senderId?: string;
  receiverId?: string;
  amountPaise?: string;
};

export class OutcomePublisher {
  private client: RedisClientType | undefined;

  constructor(private readonly config: AppConfig) {}

  async connect(): Promise<void> {
    if (this.client?.isOpen) return;
    this.client = createClient({ url: this.config.REDIS_URL });
    this.client.on("error", (error) => console.error("Redis client error", error));
    await this.client.connect();
    console.log(`[redis-publisher] connected stream=${this.config.REDIS_STREAM_NAME}`);
  }

  async publish(event: OutcomeEvent): Promise<string> {
    if (!this.client) await this.connect();
    if (!this.client) throw new Error("Redis publisher is not connected");
    return this.client.xAdd(this.config.REDIS_STREAM_NAME, "*", {
      event: JSON.stringify(event),
    });
  }

  async syncConfirmedTransaction(event: OutcomeEvent): Promise<void> {
    if (!this.client) await this.connect();
    if (!this.client || !event.senderId || !event.receiverId) throw new Error("Redis publisher is not connected or event is incomplete");
    const timestamp = Math.floor(new Date(event.occurredAt).getTime() / 1000);
    const payload = JSON.stringify(event);
    const transactionKey = `txn:${event.transactionRef}`;
    const processedKey = `processed:${event.eventRef}`;
    const multi = this.client.multi();
    multi.set(transactionKey, payload);
    multi.zAdd(`graph:${event.senderId}:out`, { score: timestamp, value: event.transactionRef });
    multi.zAdd(`graph:${event.receiverId}:in`, { score: timestamp, value: event.transactionRef });
    multi.set(processedKey, "1");
    await multi.exec();
  }

  async disconnect(): Promise<void> {
    if (this.client?.isOpen) {
      await this.client.quit();
      console.log("[redis-publisher] disconnected");
    }
    this.client = undefined;
  }
}
