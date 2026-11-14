import { createClient, type RedisClientType } from "redis";
import { config } from "./config.js";
import { OutcomePublisher, type OutcomeEvent } from "./redis.js";

type StreamMessage = { id: string; message: Record<string, string> };

/**
 * Reliable Redis Streams consumer for authoritative transaction outcomes.
 *
 * A message is acknowledged only after the graph update succeeds. Failed
 * messages remain pending and are recovered with XAUTOCLAIM after the retry
 * backoff. Messages exceeding the attempt limit are copied to the dead-letter
 * stream and then acknowledged so they cannot block the consumer group.
 */
export class OutcomeConsumer {
  private readonly client: RedisClientType;
  private readonly graphWriter: OutcomePublisher;
  private running = false;

  constructor() {
    this.client = createClient({ url: config.REDIS_URL });
    this.client.on("error", (error) => console.error("Redis consumer error", error));
    this.graphWriter = new OutcomePublisher(config);
  }

  async start(): Promise<void> {
    if (this.running) return;
    console.log(`[redis-worker] connecting stream=${config.REDIS_STREAM_NAME} group=${config.REDIS_CONSUMER_GROUP} consumer=${config.REDIS_CONSUMER_NAME}`);
    await this.client.connect();
    await this.graphWriter.connect();
    await this.ensureConsumerGroup();
    this.running = true;
    console.log("[redis-worker] started");
    void this.consumeLoop();
  }

  async stop(): Promise<void> {
    this.running = false;
    console.log("[redis-worker] stopping");
    await this.graphWriter.disconnect();
    if (this.client.isOpen) await this.client.quit();
    console.log("[redis-worker] stopped");
  }

  private async ensureConsumerGroup(): Promise<void> {
    try {
      await this.client.xGroupCreate(config.REDIS_STREAM_NAME, config.REDIS_CONSUMER_GROUP, "0", { MKSTREAM: true });
      console.log(`[redis-worker] consumer group created group=${config.REDIS_CONSUMER_GROUP}`);
    } catch (error) {
      if (!(error instanceof Error) || !error.message.includes("BUSYGROUP")) throw error;
      console.log(`[redis-worker] consumer group ready group=${config.REDIS_CONSUMER_GROUP}`);
    }
  }

  private async consumeLoop(): Promise<void> {
    while (this.running) {
      try {
        await this.recoverPending();
        const result = await this.client.xReadGroup(
          config.REDIS_CONSUMER_GROUP,
          config.REDIS_CONSUMER_NAME,
          [{ key: config.REDIS_STREAM_NAME, id: ">" }],
          { COUNT: 25, BLOCK: 1000 },
        );
        for (const stream of result ?? []) {
          console.log(`[redis-worker] received messages=${stream.messages.length} stream=${stream.name}`);
          for (const message of stream.messages) await this.processMessage(message);
        }
      } catch (error) {
        console.error("Redis consumer loop failed; retrying", error);
        await new Promise((resolve) => setTimeout(resolve, config.REDIS_RETRY_BASE_DELAY_MS));
      }
    }
  }

  private async recoverPending(): Promise<void> {
    const claimed = await this.client.xAutoClaim(
      config.REDIS_STREAM_NAME,
      config.REDIS_CONSUMER_GROUP,
      config.REDIS_CONSUMER_NAME,
      config.REDIS_RETRY_BASE_DELAY_MS,
      "0-0",
      { COUNT: 25 },
    );
    for (const message of (claimed as { messages: StreamMessage[] }).messages ?? []) {
      await this.processMessage(message);
    }
  }

  private async processMessage(message: StreamMessage): Promise<void> {
    const retryKey = `stream:retry:${config.REDIS_STREAM_NAME}:${message.id}`;
    const rawEvent = message.message.event;
    try {
      const event = JSON.parse(rawEvent) as OutcomeEvent;
      console.log(`[redis-worker] processing message=${message.id} event=${event.eventRef} transaction=${event.transactionRef}`);
      await this.graphWriter.syncConfirmedTransaction(event);
      await this.client.xAck(config.REDIS_STREAM_NAME, config.REDIS_CONSUMER_GROUP, message.id);
      await this.client.del(retryKey);
      console.log(`[redis-worker] acknowledged message=${message.id} event=${event.eventRef}`);
    } catch (error) {
      const attempts = await this.client.incr(retryKey);
      await this.client.pExpire(retryKey, 86_400_000);
      if (attempts >= config.REDIS_MAX_ATTEMPTS) {
        await this.client.xAdd(config.REDIS_DEAD_LETTER_STREAM, "*", {
          originalMessageId: message.id,
          event: rawEvent ?? "",
          attempts: String(attempts),
          error: error instanceof Error ? error.message : "unknown error",
        });
        await this.client.xAck(config.REDIS_STREAM_NAME, config.REDIS_CONSUMER_GROUP, message.id);
        await this.client.del(retryKey);
        console.error(`[redis-worker] dead-lettered message=${message.id} attempts=${attempts}`);
      } else {
        const delay = config.REDIS_RETRY_BASE_DELAY_MS * 2 ** Math.min(attempts - 1, 6);
        console.warn(`[redis-worker] retrying message=${message.id} attempt=${attempts} delayMs=${delay}`);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }
  }
}
