FROM node:22-alpine AS build
WORKDIR /repo
ARG API_INTERNAL_URL=http://localhost:8000
ENV API_INTERNAL_URL=${API_INTERNAL_URL}
COPY package.json package-lock.json* ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/api-client/package.json ./packages/api-client/package.json
RUN npm ci
COPY apps/web ./apps/web
COPY packages/api-client ./packages/api-client
RUN npm run build --workspace @readyset/web

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build --chown=node:node /repo/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=node:node /repo/apps/web/public ./apps/web/public
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
