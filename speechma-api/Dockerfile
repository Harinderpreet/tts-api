# syntax=docker/dockerfile:1

FROM node:24-bookworm-slim AS build
WORKDIR /app

# Install from the lockfile without running prepare before the source is present.
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

COPY . .
RUN npm run prepare && npm run build
RUN npm prune --omit=dev --ignore-scripts --no-audit --no-fund

FROM node:24-bookworm-slim AS production
WORKDIR /app

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000 \
    AUDIO_DIR=/app/audio_files \
    BODY_SIZE_LIMIT=1M

COPY --from=build --chown=node:node /app/build ./build
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/package.json ./package.json
COPY --chown=node:node docker/healthcheck.mjs ./docker/healthcheck.mjs

RUN mkdir -p /app/audio_files && chown node:node /app/audio_files
USER node

EXPOSE 3000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=6s --start-period=30s --retries=3 \
  CMD ["node", "docker/healthcheck.mjs"]

# The hosting platform supplies runtime variables; no .env file is baked into the image.
CMD ["node", "build"]
