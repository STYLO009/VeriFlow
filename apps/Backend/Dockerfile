FROM oven/bun:1.4.2-alpine

WORKDIR /app

COPY package.json bun.lock ./
COPY apps/Backend/package.json ./apps/Backend/package.json
COPY packages ./packages
RUN bun install --frozen-lockfile

COPY apps/Backend ./apps/Backend

WORKDIR /app/apps/Backend
RUN bun --bun run prisma generate
RUN bun run build

RUN addgroup -S appgroup && adduser -S appuser -G appgroup
RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 4000
CMD ["bun", "run", "start"]
