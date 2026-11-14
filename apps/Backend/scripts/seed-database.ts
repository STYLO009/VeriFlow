import "dotenv/config";
import bcrypt from "bcryptjs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { prisma } from "../src/prisma.js";
import { config } from "../src/config.js";

type CredentialRow = { role: string; email: string; password: string };
type DatasetEvent = {
  event_id: string;
  transaction_id: string;
  source_account: string;
  destination_account: string;
  amount: number;
  timestamp: number;
  metadata?: { is_fraud?: number };
};

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

function parseCredentials(markdown: string): CredentialRow[] {
  return markdown
    .split(/\r?\n/)
    .filter((line) => line.trim().startsWith("|") && !line.includes("---"))
    .slice(1)
    .map((line) => line.split("|").slice(1, -1).map((value) => value.trim()))
    .filter((cells): cells is [string, string, string] => cells.length === 3 && cells.every(Boolean))
    .map(([role, email, password]) => ({ role, email: email.toLowerCase(), password }));
}

async function main(): Promise<void> {
  const credentials = parseCredentials(await readFile(path.join(repoRoot, "credentials.txt"), "utf8"));
  const dataset = JSON.parse(await readFile(path.join(repoRoot, "mulegraph", "data", "live_demo_events.json"), "utf8")) as { events: DatasetEvent[] };
  if (credentials.length === 0) throw new Error("No credential rows found in credentials.txt");
  if (dataset.events.length === 0) throw new Error("No events found in live_demo_events.json");

  for (const credential of credentials) {
    const passwordHash = await bcrypt.hash(credential.password, config.BCRYPT_SALT_ROUNDS);
    await prisma.user.upsert({
      where: { email: credential.email },
      update: { passwordHash, role: credential.role as never, isActive: true },
      create: { email: credential.email, passwordHash, role: credential.role as never, isActive: true },
    });
  }

  for (const event of dataset.events) {
    const sender = await prisma.account.upsert({
      where: { accountRef: event.source_account },
      update: {},
      create: { accountRef: event.source_account },
    });
    const receiver = await prisma.account.upsert({
      where: { accountRef: event.destination_account },
      update: {},
      create: { accountRef: event.destination_account },
    });
    await prisma.transaction.upsert({
      where: { transactionRef: event.transaction_id },
      update: { senderId: sender.id, receiverId: receiver.id, amountPaise: BigInt(Math.round(event.amount * 100)), eventTimestamp: new Date(event.timestamp * 1000), status: "SUCCESS" },
      create: { transactionRef: event.transaction_id, senderId: sender.id, receiverId: receiver.id, amountPaise: BigInt(Math.round(event.amount * 100)), eventTimestamp: new Date(event.timestamp * 1000), status: "SUCCESS" },
    });
    if (event.metadata?.is_fraud === 1) {
      await prisma.riskDecision.create({
        data: {
          transactionRef: event.transaction_id,
          riskScore: 85,
          decision: "ESCALATE",
          modelVersion: "paysim-seed-v1",
          evidence: { source: "mtalaltariq/paysim-data", isFraud: true },
        },
      });
      await prisma.fraudSignal.create({
        data: {
          transactionRef: event.transaction_id,
          patternType: "PAYSIM_FRAUD_LABEL",
          severity: "HIGH",
          involvedAccountIds: [event.source_account, event.destination_account],
          evidenceTransactionIds: [event.transaction_id],
          features: { source: "mtalaltariq/paysim-data", isFraud: true },
        },
      });
    }
  }

  console.log(`Seeded ${credentials.length} users, ${dataset.events.length} transactions, and ${new Set(dataset.events.flatMap((event) => [event.source_account, event.destination_account])).size} accounts.`);
}

try {
  await main();
} finally {
  await prisma.$disconnect();
}

