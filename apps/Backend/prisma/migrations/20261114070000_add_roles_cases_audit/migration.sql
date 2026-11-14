-- Expand role model while preserving existing users.
ALTER TYPE "UserRole" RENAME TO "UserRole_old";

CREATE TYPE "UserRole" AS ENUM (
  'SUPER_ADMIN',
  'FRAUD_ANALYST',
  'INVESTIGATOR',
  'COMPLIANCE_OFFICER',
  'AUDITOR_VIEWER'
);

ALTER TABLE "User" ALTER COLUMN "role" DROP DEFAULT;
ALTER TABLE "User"
  ALTER COLUMN "role" TYPE "UserRole"
  USING (
    CASE "role"::text
      WHEN 'ADMIN' THEN 'SUPER_ADMIN'
      ELSE 'FRAUD_ANALYST'
    END
  )::"UserRole";

DROP TYPE "UserRole_old";
ALTER TABLE "User" ALTER COLUMN "role" SET DEFAULT 'FRAUD_ANALYST';

CREATE TYPE "InvestigationCaseStatus" AS ENUM (
  'OPEN',
  'IN_REVIEW',
  'ESCALATED',
  'RESOLVED',
  'CLOSED'
);

CREATE TABLE "InvestigationCase" (
  "id" TEXT NOT NULL,
  "caseRef" TEXT NOT NULL,
  "title" TEXT NOT NULL,
  "description" TEXT,
  "status" "InvestigationCaseStatus" NOT NULL DEFAULT 'OPEN',
  "priority" TEXT NOT NULL DEFAULT 'MEDIUM',
  "accountRefs" JSONB NOT NULL,
  "transactionRefs" JSONB NOT NULL,
  "findings" JSONB,
  "assigneeId" TEXT,
  "createdById" TEXT NOT NULL,
  "resolvedAt" TIMESTAMP(3),
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "InvestigationCase_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "AuditLog" (
  "id" TEXT NOT NULL,
  "actorId" TEXT,
  "action" TEXT NOT NULL,
  "resource" TEXT NOT NULL,
  "resourceId" TEXT,
  "metadata" JSONB,
  "requestId" TEXT,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "AuditLog_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "InvestigationCase_caseRef_key" ON "InvestigationCase"("caseRef");
CREATE INDEX "InvestigationCase_status_priority_createdAt_idx" ON "InvestigationCase"("status", "priority", "createdAt");
CREATE INDEX "InvestigationCase_assigneeId_status_idx" ON "InvestigationCase"("assigneeId", "status");
CREATE INDEX "AuditLog_actorId_createdAt_idx" ON "AuditLog"("actorId", "createdAt");
CREATE INDEX "AuditLog_resource_resourceId_createdAt_idx" ON "AuditLog"("resource", "resourceId", "createdAt");
CREATE INDEX "AuditLog_action_createdAt_idx" ON "AuditLog"("action", "createdAt");

ALTER TABLE "InvestigationCase"
  ADD CONSTRAINT "InvestigationCase_assigneeId_fkey"
  FOREIGN KEY ("assigneeId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "InvestigationCase"
  ADD CONSTRAINT "InvestigationCase_createdById_fkey"
  FOREIGN KEY ("createdById") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "AuditLog"
  ADD CONSTRAINT "AuditLog_actorId_fkey"
  FOREIGN KEY ("actorId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
