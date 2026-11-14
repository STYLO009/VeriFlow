-- CreateEnum
CREATE TYPE "TransactionStatus" AS ENUM ('PENDING', 'SUCCESS', 'FAILED', 'REVERSED');

-- CreateEnum
CREATE TYPE "RiskDecisionType" AS ENUM ('ALLOW', 'MONITOR', 'REVIEW', 'ESCALATE');

-- CreateTable
CREATE TABLE "Account" (
    "id" TEXT NOT NULL,
    "accountRef" TEXT NOT NULL,
    "accountAgeDays" INTEGER,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Account_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Transaction" (
    "id" TEXT NOT NULL,
    "transactionRef" TEXT NOT NULL,
    "senderId" TEXT NOT NULL,
    "receiverId" TEXT NOT NULL,
    "amountPaise" BIGINT NOT NULL,
    "eventTimestamp" TIMESTAMP(3) NOT NULL,
    "status" "TransactionStatus" NOT NULL,
    "originalTransactionRef" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Transaction_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RiskDecision" (
    "id" TEXT NOT NULL,
    "transactionRef" TEXT NOT NULL,
    "riskScore" DOUBLE PRECISION NOT NULL,
    "decision" "RiskDecisionType" NOT NULL,
    "modelVersion" TEXT NOT NULL,
    "evidence" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "RiskDecision_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "FraudSignal" (
    "id" TEXT NOT NULL,
    "transactionRef" TEXT,
    "patternType" TEXT NOT NULL,
    "severity" TEXT NOT NULL,
    "involvedAccountIds" JSONB NOT NULL,
    "evidenceTransactionIds" JSONB NOT NULL,
    "features" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "FraudSignal_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ProcessingEvent" (
    "id" TEXT NOT NULL,
    "eventRef" TEXT NOT NULL,
    "transactionRef" TEXT NOT NULL,
    "eventType" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "attemptCount" INTEGER NOT NULL DEFAULT 0,
    "errorMessage" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "processedAt" TIMESTAMP(3),

    CONSTRAINT "ProcessingEvent_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AccountRiskHistory" (
    "id" TEXT NOT NULL,
    "accountRef" TEXT NOT NULL,
    "riskScore" DOUBLE PRECISION NOT NULL,
    "modelVersion" TEXT NOT NULL,
    "evidence" JSONB NOT NULL,
    "calculatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AccountRiskHistory_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "Account_accountRef_key" ON "Account"("accountRef");

-- CreateIndex
CREATE INDEX "Account_accountRef_idx" ON "Account"("accountRef");

-- CreateIndex
CREATE UNIQUE INDEX "Transaction_transactionRef_key" ON "Transaction"("transactionRef");

-- CreateIndex
CREATE INDEX "Transaction_senderId_eventTimestamp_idx" ON "Transaction"("senderId", "eventTimestamp");

-- CreateIndex
CREATE INDEX "Transaction_receiverId_eventTimestamp_idx" ON "Transaction"("receiverId", "eventTimestamp");

-- CreateIndex
CREATE INDEX "Transaction_status_eventTimestamp_idx" ON "Transaction"("status", "eventTimestamp");

-- CreateIndex
CREATE INDEX "Transaction_originalTransactionRef_idx" ON "Transaction"("originalTransactionRef");

-- CreateIndex
CREATE INDEX "RiskDecision_transactionRef_idx" ON "RiskDecision"("transactionRef");

-- CreateIndex
CREATE INDEX "RiskDecision_createdAt_idx" ON "RiskDecision"("createdAt");

-- CreateIndex
CREATE INDEX "FraudSignal_patternType_idx" ON "FraudSignal"("patternType");

-- CreateIndex
CREATE INDEX "FraudSignal_createdAt_idx" ON "FraudSignal"("createdAt");

-- CreateIndex
CREATE INDEX "FraudSignal_transactionRef_idx" ON "FraudSignal"("transactionRef");

-- CreateIndex
CREATE UNIQUE INDEX "ProcessingEvent_eventRef_key" ON "ProcessingEvent"("eventRef");

-- CreateIndex
CREATE INDEX "ProcessingEvent_transactionRef_idx" ON "ProcessingEvent"("transactionRef");

-- CreateIndex
CREATE INDEX "ProcessingEvent_status_createdAt_idx" ON "ProcessingEvent"("status", "createdAt");

-- CreateIndex
CREATE INDEX "AccountRiskHistory_accountRef_calculatedAt_idx" ON "AccountRiskHistory"("accountRef", "calculatedAt");

-- AddForeignKey
ALTER TABLE "Transaction" ADD CONSTRAINT "Transaction_senderId_fkey" FOREIGN KEY ("senderId") REFERENCES "Account"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Transaction" ADD CONSTRAINT "Transaction_receiverId_fkey" FOREIGN KEY ("receiverId") REFERENCES "Account"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Transaction" ADD CONSTRAINT "Transaction_originalTransactionRef_fkey" FOREIGN KEY ("originalTransactionRef") REFERENCES "Transaction"("transactionRef") ON DELETE SET NULL ON UPDATE CASCADE;
