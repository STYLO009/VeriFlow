import { randomUUID } from "node:crypto";
import { Router } from "express";
import { z } from "zod";
import { prisma } from "./prisma.js";
import { GraphEngineClient } from "./graph-engine.js";
import { OutcomePublisher } from "./redis.js";
import { AppError, isPrismaForeignKeyError, isPrismaNotFoundError, isPrismaUniqueError } from "./errors.js";
import { RiskDecisionType } from "../generated/prisma/enums.js";
import { trustedOutcomeSource } from "./middleware.js";
import { requireRoles } from "./auth.js";
import rateLimit from "express-rate-limit";
import { GeminiReportClient } from "./gemini.js";

const auditReportLimiter = rateLimit({ windowMs: 60_000, limit: 5, standardHeaders: "draft-7", legacyHeaders: false });

const transactionSchema = z.object({
  transactionId: z.string().trim().min(1).max(100),
  senderId: z.string().trim().min(1).max(100),
  receiverId: z.string().trim().min(1).max(100),
  amountPaise: z.number().int().positive().safe(),
  currency: z.string().trim().length(3).default("INR"),
  eventTimestamp: z.string().datetime({ offset: true }),
});

const listQuery = z.object({
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(100).default(25),
  status: z.enum(["PENDING", "SUCCESS", "FAILED", "REVERSED"]).optional(),
  accountId: z.string().trim().min(1).optional(),
});

function serialize(value: unknown): unknown {
  return JSON.parse(JSON.stringify(value, (_, item) => (typeof item === "bigint" ? item.toString() : item)));
}

export function createApiRouter(graphEngine: GraphEngineClient, publisher: OutcomePublisher, gemini = new GeminiReportClient(process.env.GEMINI_API_KEY, process.env.GEMINI_MODEL ?? "gemini-2.5-flash")): Router {
  const router = Router();

  router.get("/health", async (_req, res, next) => {
    try {
      await prisma.$queryRaw`SELECT 1`;
      res.json({ status: "ok", database: "ok", graphEngine: "external" });
    } catch (error) {
      next(new AppError("DATABASE_UNAVAILABLE", 503, "Database is unavailable.", error));
    }
  });

  router.post("/transactions/evaluate", requireRoles("SUPER_ADMIN", "FRAUD_ANALYST", "INVESTIGATOR"), async (req, res, next) => {
    try {
      const input = transactionSchema.parse(req.body);
      const requestId = res.locals.requestId as string;
      const existing = await prisma.transaction.findUnique({
        where: { transactionRef: input.transactionId },
        include: { sender: true, receiver: true },
      });
      if (existing) {
        const sameRequest =
          existing.sender.accountRef === input.senderId &&
          existing.receiver.accountRef === input.receiverId &&
          existing.amountPaise === BigInt(input.amountPaise) &&
          existing.eventTimestamp.getTime() === new Date(input.eventTimestamp).getTime();
        if (!sameRequest) {
          throw new AppError("TRANSACTION_CONFLICT", 409, "Transaction id already belongs to different transaction data.");
        }
        const risk = await prisma.riskDecision.findFirst({
          where: { transactionRef: input.transactionId },
          orderBy: { createdAt: "desc" },
        });
        res.status(200).json({
          transactionId: input.transactionId,
          riskScore: risk?.riskScore ?? 0,
          decision: risk?.decision ?? "ALLOW",
          processingStatus: "COMPLETE",
          patterns: [],
          evidence: risk?.evidence ?? {},
          modelVersion: risk?.modelVersion ?? "stored-transaction",
          alreadyExists: true,
          transaction: serialize(existing),
        });
        return;
      }
      const evaluation = await graphEngine.evaluate(input, requestId);
      const transaction = await prisma.$transaction(async (tx) => {
        const [sender, receiver] = await Promise.all([
          tx.account.upsert({ where: { accountRef: input.senderId }, update: {}, create: { accountRef: input.senderId } }),
          tx.account.upsert({ where: { accountRef: input.receiverId }, update: {}, create: { accountRef: input.receiverId } }),
        ]);
        const saved = await tx.transaction.create({
          data: {
            transactionRef: input.transactionId,
            senderId: sender.id,
            receiverId: receiver.id,
            amountPaise: BigInt(input.amountPaise),
            eventTimestamp: new Date(input.eventTimestamp),
            status: "PENDING",
          },
        });
        await tx.riskDecision.create({
          data: {
            transactionRef: input.transactionId,
            riskScore: evaluation.riskScore,
            decision: evaluation.decision,
            modelVersion: evaluation.modelVersion,
            evidence: evaluation.evidence as object,
          },
        });
        await tx.fraudSignal.createMany({
          data: evaluation.patterns.filter((pattern) => pattern.detected !== false).map((pattern) => ({
            transactionRef: input.transactionId,
            patternType: pattern.name,
            severity: pattern.severity,
            involvedAccountIds: (pattern.accountIds ?? []) as object,
            evidenceTransactionIds: (pattern.transactionIds ?? []) as object,
            features: (pattern.features ?? {}) as object,
          })),
        });
        return saved;
      });
      res.status(201).json({ ...evaluation, processingStatus: evaluation.processingStatus, transaction: serialize(transaction) });
    } catch (error) {
      if (isPrismaUniqueError(error)) {
        // Handle concurrent retries that both passed the initial lookup.
        const transactionId = typeof req.body?.transactionId === "string" ? req.body.transactionId : "";
        const existing = transactionId
          ? await prisma.transaction.findUnique({ where: { transactionRef: transactionId }, include: { sender: true, receiver: true } })
          : null;
        if (existing) {
          const risk = await prisma.riskDecision.findFirst({ where: { transactionRef: transactionId }, orderBy: { createdAt: "desc" } });
          res.status(200).json({
            transactionId,
            riskScore: risk?.riskScore ?? 0,
            decision: risk?.decision ?? "ALLOW",
            processingStatus: "COMPLETE",
            patterns: [],
            evidence: risk?.evidence ?? {},
            modelVersion: risk?.modelVersion ?? "stored-transaction",
            alreadyExists: true,
            transaction: serialize(existing),
          });
        } else next(new AppError("TRANSACTION_ALREADY_EXISTS", 409, "Transaction already exists."));
      } else next(error);
    }
  });

  const publishOutcome = async (req: any, res: any, next: any) => {
    try {
       const input = z.object({
         transactionId: z.string().trim().min(1),
         status: z.enum(["SUCCESS", "FAILED", "REVERSED"]),
         originalTransactionId: z.string().trim().min(1).optional(),
       }).parse(req.body);
       const eventRef = req.header("x-event-id")?.trim() || randomUUID();
       const existingEvent = await prisma.processingEvent.findUnique({ where: { eventRef } });
       if (existingEvent) {
         res.status(200).json({ status: "already_processed", eventRef });
         return;
       }
       const transaction = await prisma.transaction.update({
         where: { transactionRef: input.transactionId },
         data: { status: input.status, originalTransactionRef: input.originalTransactionId },
         include: { sender: true, receiver: true },
       });
       const event = {
         eventRef,
         transactionRef: input.transactionId,
         status: input.status,
         occurredAt: new Date().toISOString(),
         originalTransactionRef: input.originalTransactionId,
         senderId: transaction.sender.accountRef,
         receiverId: transaction.receiver.accountRef,
         amountPaise: transaction.amountPaise.toString(),
       };
       await prisma.processingEvent.create({
        data: {
           eventRef,
          transactionRef: input.transactionId,
          eventType: "TRANSACTION_OUTCOME",
           status: "PENDING",
         },
       });
       let streamId: string;
       try {
         await publisher.syncConfirmedTransaction(event);
         streamId = await publisher.publish(event);
       } catch (publishError) {
         await prisma.processingEvent.update({
           where: { eventRef },
           data: {
             status: "FAILED",
             attemptCount: { increment: 1 },
             errorMessage: publishError instanceof Error ? publishError.message : "Redis publishing failed.",
           },
         }).catch(() => undefined);
         throw new AppError("REDIS_UNAVAILABLE", 503, "Transaction outcome could not be published.", publishError);
       }
       await prisma.processingEvent.update({ where: { eventRef }, data: { status: "COMPLETED", processedAt: new Date() } });
       res.json({ transaction: serialize(transaction), streamId, eventRef });
    } catch (error) {
      if (error instanceof AppError) next(error);
      else if (isPrismaNotFoundError(error)) next(new AppError("NOT_FOUND", 404, "Transaction not found."));
      else next(error);
    }
  };
  router.post("/transactions/outcome", requireRoles("SUPER_ADMIN", "FRAUD_ANALYST"), trustedOutcomeSource, publishOutcome);
  router.post("/transactions/outcomes", requireRoles("SUPER_ADMIN", "FRAUD_ANALYST"), trustedOutcomeSource, publishOutcome);

  router.get("/transactions", async (req, res, next) => {
    try {
      const query = listQuery.parse(req.query);
      const where = {
        ...(query.status ? { status: query.status } : {}),
        ...(query.accountId ? { OR: [{ sender: { accountRef: query.accountId } }, { receiver: { accountRef: query.accountId } }] } : {}),
      };
      const [items, total] = await Promise.all([
        prisma.transaction.findMany({
          where,
          include: { sender: true, receiver: true },
          orderBy: { eventTimestamp: "desc" },
          skip: (query.page - 1) * query.pageSize,
          take: query.pageSize,
        }),
        prisma.transaction.count({ where }),
      ]);
      res.json({ items: serialize(items), page: query.page, pageSize: query.pageSize, total, totalPages: Math.ceil(total / query.pageSize) });
    } catch (error) { next(error); }
  });

  router.get("/transactions/:id", async (req, res, next) => {
    try {
      const transaction = await prisma.transaction.findFirst({
        where: { OR: [{ id: req.params.id }, { transactionRef: req.params.id }] },
        include: { sender: true, receiver: true },
      });
      if (!transaction) throw new AppError("NOT_FOUND", 404, "Transaction not found.");
      const [risk, signals] = await Promise.all([
        prisma.riskDecision.findFirst({ where: { transactionRef: transaction.transactionRef }, orderBy: { createdAt: "desc" } }),
        prisma.fraudSignal.findMany({ where: { transactionRef: transaction.transactionRef }, orderBy: { createdAt: "desc" } }),
      ]);
      res.json({ transaction: serialize(transaction), risk: serialize(risk), signals: serialize(signals) });
    } catch (error) { next(error); }
  });

  router.get("/accounts", async (req, res, next) => {
    try {
      const query = listQuery.pick({ page: true, pageSize: true }).parse(req.query);
      const [items, total] = await Promise.all([
        prisma.account.findMany({
          orderBy: { createdAt: "desc" },
          skip: (query.page - 1) * query.pageSize,
          take: query.pageSize,
          include: { _count: { select: { sentTransactions: true, receivedTransactions: true } } },
        }),
        prisma.account.count(),
      ]);
      res.json({ items: serialize(items), page: query.page, pageSize: query.pageSize, total, totalPages: Math.ceil(total / query.pageSize) });
    } catch (error) { next(error); }
  });

  router.get("/accounts/:id", async (req, res, next) => {
    try {
      const account = await prisma.account.findFirst({
        where: { OR: [{ id: req.params.id }, { accountRef: req.params.id }] },
        include: { sentTransactions: { take: 10, orderBy: { eventTimestamp: "desc" } }, receivedTransactions: { take: 10, orderBy: { eventTimestamp: "desc" } } },
      });
      if (!account) throw new AppError("NOT_FOUND", 404, "Account not found.");
      res.json(serialize(account));
    } catch (error) { next(error); }
  });

  router.get("/graph/:accountId", async (req, res, next) => {
    try {
      const window = z.enum(["5s", "30s", "5m", "1h", "24h"]).default("5m").parse(req.query.window);
      const engine = graphEngine as GraphEngineClient;
      const graph = await engine.neighborhood(req.params.accountId, window, res.locals.requestId as string);
      res.json({ accountId: req.params.accountId, ...graph });
    } catch (error) {
      next(error);
    }
  });

  router.get("/risk/:transactionId", async (req, res, next) => {
    try {
      const risk = await prisma.riskDecision.findFirst({ where: { transactionRef: req.params.transactionId }, orderBy: { createdAt: "desc" } });
      if (!risk) throw new AppError("NOT_FOUND", 404, "Risk decision not found.");
      const signals = await prisma.fraudSignal.findMany({ where: { transactionRef: req.params.transactionId }, orderBy: { createdAt: "desc" } });
      res.json({ ...serialize(risk) as object, signals: serialize(signals) });
    } catch (error) { next(error); }
  });

  router.get("/alerts", async (req, res, next) => {
    try {
      const query = listQuery.pick({ page: true, pageSize: true }).parse(req.query);
       const where = { decision: { in: [RiskDecisionType.REVIEW, RiskDecisionType.ESCALATE] } };
      const [items, total] = await Promise.all([
        prisma.riskDecision.findMany({ where, orderBy: { createdAt: "desc" }, skip: (query.page - 1) * query.pageSize, take: query.pageSize }),
        prisma.riskDecision.count({ where }),
      ]);
      const refs = items.map((item) => item.transactionRef);
      const signals = refs.length ? await prisma.fraudSignal.findMany({ where: { transactionRef: { in: refs } }, orderBy: { createdAt: "desc" } }) : [];
      const byTransaction = new Map<string, typeof signals>();
      for (const signal of signals) {
        if (!signal.transactionRef) continue;
        const current = byTransaction.get(signal.transactionRef) ?? [];
        current.push(signal);
        byTransaction.set(signal.transactionRef, current);
      }
      res.json({ items: items.map((item) => ({ ...serialize(item) as object, signals: serialize(byTransaction.get(item.transactionRef) ?? []) })), page: query.page, pageSize: query.pageSize, total, totalPages: Math.ceil(total / query.pageSize) });
    } catch (error) { next(error); }
  });

  router.get("/dashboard/overview", async (_req, res, next) => {
    try {
      const [transactions, accounts, alerts, volume] = await Promise.all([
        prisma.transaction.count(),
        prisma.account.count(),
        prisma.riskDecision.count({ where: { decision: { in: ["REVIEW", "ESCALATE"] } } }),
        prisma.transaction.aggregate({ _sum: { amountPaise: true }, where: { status: "SUCCESS" } }),
      ]);
      res.json({ transactions, accounts, alerts, settledVolumePaise: volume._sum.amountPaise?.toString() ?? "0" });
    } catch (error) { next(error); }
  });

  router.get("/cases", async (req, res, next) => {
    try {
      const query = listQuery.pick({ page: true, pageSize: true }).parse(req.query);
      const [items, total] = await Promise.all([
        prisma.investigationCase.findMany({ orderBy: { createdAt: "desc" }, skip: (query.page - 1) * query.pageSize, take: query.pageSize, include: { assignee: { select: { id: true, email: true, role: true } } } }),
        prisma.investigationCase.count(),
      ]);
      res.json({ items: serialize(items), page: query.page, pageSize: query.pageSize, total, totalPages: Math.ceil(total / query.pageSize) });
    } catch (error) { next(error); }
  });

  router.post("/cases", requireRoles("SUPER_ADMIN", "INVESTIGATOR", "COMPLIANCE_OFFICER"), async (req, res, next) => {
    try {
      const input = z.object({
        title: z.string().trim().min(1).max(200),
        description: z.string().trim().max(5000).optional(),
        priority: z.enum(["LOW", "MEDIUM", "HIGH", "CRITICAL"]).default("MEDIUM"),
        accountRefs: z.array(z.string().trim().min(1)).default([]),
        transactionRefs: z.array(z.string().trim().min(1)).default([]),
        assigneeId: z.string().uuid().optional(),
      }).parse(req.body);
      const created = await prisma.investigationCase.create({
        data: {
          caseRef: `CASE-${randomUUID().slice(0, 8).toUpperCase()}`,
          title: input.title,
          description: input.description,
          priority: input.priority,
          accountRefs: input.accountRefs as object,
          transactionRefs: input.transactionRefs as object,
          assigneeId: input.assigneeId,
          createdById: req.user!.userId,
        },
      });
      await prisma.auditLog.create({ data: { actorId: req.user!.userId, action: "CASE_CREATED", resource: "InvestigationCase", resourceId: created.id, requestId: res.locals.requestId as string } });
      res.status(201).json(serialize(created));
    } catch (error) {
      if (isPrismaForeignKeyError(error)) next(new AppError("VALIDATION_ERROR", 422, "The assigned user does not exist."));
      else next(error);
    }
  });

  router.get("/cases/:id", async (req, res, next) => {
    try {
      const item = await prisma.investigationCase.findFirst({ where: { OR: [{ id: req.params.id }, { caseRef: req.params.id }] }, include: { assignee: { select: { id: true, email: true, role: true } }, createdBy: { select: { id: true, email: true, role: true } } } });
      if (!item) throw new AppError("NOT_FOUND", 404, "Investigation case not found.");
      res.json(serialize(item));
    } catch (error) { next(error); }
  });

  router.patch("/cases/:id", requireRoles("SUPER_ADMIN", "INVESTIGATOR", "COMPLIANCE_OFFICER"), async (req, res, next) => {
    try {
      const input = z.object({ status: z.enum(["OPEN", "IN_REVIEW", "ESCALATED", "RESOLVED", "CLOSED"]).optional(), findings: z.record(z.unknown()).optional(), assigneeId: z.string().uuid().nullable().optional() }).parse(req.body);
      const item = await prisma.investigationCase.update({ where: { id: req.params.id }, data: { ...input, findings: input.findings as object | undefined, resolvedAt: input.status === "RESOLVED" || input.status === "CLOSED" ? new Date() : undefined } });
      await prisma.auditLog.create({ data: { actorId: req.user!.userId, action: "CASE_UPDATED", resource: "InvestigationCase", resourceId: item.id, requestId: res.locals.requestId as string, metadata: input as object } });
      res.json(serialize(item));
    } catch (error) {
      if (isPrismaNotFoundError(error)) next(new AppError("NOT_FOUND", 404, "Investigation case not found."));
      else if (isPrismaForeignKeyError(error)) next(new AppError("VALIDATION_ERROR", 422, "The assigned user does not exist."));
      else next(error);
    }
  });

  router.get("/audit-logs", requireRoles("SUPER_ADMIN", "COMPLIANCE_OFFICER", "AUDITOR_VIEWER"), async (req, res, next) => {
    try {
      const query = listQuery.pick({ page: true, pageSize: true }).parse(req.query);
      const [items, total] = await Promise.all([
        prisma.auditLog.findMany({ orderBy: { createdAt: "desc" }, skip: (query.page - 1) * query.pageSize, take: query.pageSize, include: { actor: { select: { id: true, email: true, role: true } } } }),
        prisma.auditLog.count(),
      ]);
      res.json({ items: serialize(items), page: query.page, pageSize: query.pageSize, total, totalPages: Math.ceil(total / query.pageSize) });
    } catch (error) { next(error); }
  });

  router.post("/audit-reports/daily", auditReportLimiter, requireRoles("SUPER_ADMIN", "COMPLIANCE_OFFICER", "AUDITOR_VIEWER"), async (req, res, next) => {
    try {
      const input = z.object({ date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional() }).parse(req.body ?? {});
      const date = input.date ?? new Date().toISOString().slice(0, 10);
      const start = new Date(`${date}T00:00:00.000Z`);
      const end = new Date(start.getTime() + 86_400_000);
      if (Number.isNaN(start.getTime())) throw new AppError("VALIDATION_ERROR", 400, "Invalid report date.");
      const logs = await prisma.auditLog.findMany({
        where: { createdAt: { gte: start, lt: end } },
        orderBy: { createdAt: "asc" },
        take: 1000,
        include: { actor: { select: { email: true } } },
      });
      const records = logs.map((log) => ({ action: log.action, resource: log.resource, resourceId: log.resourceId, createdAt: log.createdAt.toISOString(), actorEmail: log.actor?.email ?? null, metadata: log.metadata }));
      const report = await gemini.generateDailyAuditReport(date, records);
      res.json({ date, eventCount: records.length, generatedAt: new Date().toISOString(), report });
    } catch (error) {
      next(error);
    }
  });

  return router;
}
