import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";
import { Router, type RequestHandler } from "express";
import { z } from "zod";
import { prisma } from "./prisma.js";
import { config } from "./config.js";
import { AppError } from "./errors.js";

const credentialsSchema = z.object({
  email: z.string().trim().email().transform((value) => value.toLowerCase()),
  password: z.string().min(8).max(200),
});

export type AppRole = "SUPER_ADMIN" | "FRAUD_ANALYST" | "INVESTIGATOR" | "COMPLIANCE_OFFICER" | "AUDITOR_VIEWER";

function tokenFor(user: { id: string; role: AppRole }): string {
  return jwt.sign({ sub: user.id, role: user.role }, config.JWT_SECRET, { expiresIn: config.JWT_EXPIRES_IN as jwt.SignOptions["expiresIn"] });
}

export const requireAuth: RequestHandler = (request, _response, next) => {
  const value = request.header("authorization");
  if (!value?.startsWith("Bearer ")) {
    next(new AppError("UNAUTHORIZED", 401, "Authentication is required."));
    return;
  }
  try {
    const payload = jwt.verify(value.slice(7), config.JWT_SECRET) as { sub?: string; role?: AppRole };
    if (!payload.sub || !payload.role) throw new Error("invalid token");
    request.user = { userId: payload.sub, role: payload.role };
    next();
  } catch {
    next(new AppError("UNAUTHORIZED", 401, "Authentication token is invalid or expired."));
  }
};

export function requireRoles(...roles: AppRole[]): RequestHandler {
  return (request, _response, next) => {
    if (!request.user || !roles.includes(request.user.role)) {
      next(new AppError("FORBIDDEN", 403, "This role is not allowed to perform the requested action."));
      return;
    }
    next();
  };
}

export function createAuthRouter(): Router {
  const router = Router();

  router.post("/register", async (request, response, next) => {
    try {
      const input = credentialsSchema.parse(request.body);
      const count = await prisma.user.count();
      const passwordHash = await bcrypt.hash(input.password, config.BCRYPT_SALT_ROUNDS);
      const user = await prisma.user.create({
        data: { email: input.email, passwordHash, role: count === 0 ? "SUPER_ADMIN" : "FRAUD_ANALYST" },
        select: { id: true, email: true, role: true },
      });
      response.status(201).json({ user, token: tokenFor(user) });
    } catch (error) {
      if (typeof error === "object" && error !== null && "code" in error && (error as { code?: string }).code === "P2002") {
        next(new AppError("EMAIL_ALREADY_EXISTS", 409, "An account with that email already exists."));
      } else next(error);
    }
  });

  router.post("/login", async (request, response, next) => {
    try {
      const input = credentialsSchema.parse(request.body);
      const user = await prisma.user.findUnique({ where: { email: input.email } });
      if (!user || !user.isActive || !(await bcrypt.compare(input.password, user.passwordHash))) {
        throw new AppError("UNAUTHORIZED", 401, "Invalid email or password.");
      }
      await prisma.user.update({ where: { id: user.id }, data: { lastLoginAt: new Date() } });
      response.json({ user: { id: user.id, email: user.email, role: user.role }, token: tokenFor(user) });
    } catch (error) {
      next(error);
    }
  });

  router.get("/me", requireAuth, async (request, response, next) => {
    try {
      const user = await prisma.user.findUnique({ where: { id: request.user!.userId }, select: { id: true, email: true, role: true, isActive: true } });
      if (!user) throw new AppError("NOT_FOUND", 404, "User not found.");
      response.json({ user });
    } catch (error) {
      next(error);
    }
  });

  return router;
}
