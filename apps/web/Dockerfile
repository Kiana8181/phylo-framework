# apps/web/Dockerfile

# --- Build stage ---
# Use Debian (glibc) instead of Alpine (musl) because Next/SWC can crash
# with SIGBUS during production builds on Alpine in some environments.
FROM node:20-bookworm-slim AS build
WORKDIR /srv

# Copy manifests first for caching
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json

# Make npm resilient to flaky networks
RUN npm config set fetch-retries 5 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && npm config set fetch-timeout 120000 \
    && npm config set prefer-online true \
    && npm config set audit false \
    && npm config set fund false

# Install all workspaces deps according to lockfile
# If your lockfile was created without -ws, regenerate it locally with: npm i -ws
RUN npm ci --workspaces --no-audit --fund=false

# Copy the rest of the repo
COPY . .

# Ensure Next uses standalone output (you can also set this in next.config.js)
# If you already set `output: 'standalone'` in next.config.js, this ENV is not needed.
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_OUTPUT=standalone
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

# Build contracts first (adjust workspace name if different)
RUN npm -w @phylo/contracts run build

# Build the web app (adjust workspace name if different)
RUN npm -w web run build

# --- Runtime stage (no npm install here) ---
FROM node:20-bookworm-slim AS runtime
WORKDIR /srv
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
EXPOSE 3000

# Copy standalone server with minimal node_modules produced by Next
# Path structure created by Next when output:'standalone'
COPY --from=build /srv/apps/web/.next/standalone /srv
# Static assets
COPY --from=build /srv/apps/web/.next/static /srv/apps/web/.next/static
COPY --from=build /srv/apps/web/public /srv/apps/web/public

# Contracts JSON/types if your server needs them at runtime; keep in sync with API/Dowser
COPY --from=build /srv/packages/contracts /srv/packages/contracts

# Next standalone produces server.js at /srv/apps/web/server.js
CMD ["node", "apps/web/server.js"]
