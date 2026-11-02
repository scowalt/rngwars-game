
FROM oven/bun:1.4.2-alpine AS frontend-builder
WORKDIR /app
COPY package.json bun.lock ./
COPY apps/frontend/package.json ./apps/frontend/package.json
COPY apps/marketing_site/package.json ./apps/marketing_site/package.json
RUN bun install --frozen-lockfile --filter @rngwars/frontend
COPY apps/frontend/index.html apps/frontend/tsconfig.json apps/frontend/vite.config.ts ./apps/frontend/
COPY apps/frontend/src/ ./apps/frontend/src/
WORKDIR /app/apps/frontend
ARG VITE_POSTHOG_KEY
ARG VITE_SENTRY_DSN
RUN bun run build

FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine AS api-builder
WORKDIR /app
COPY apps/api/ ./apps/api/
RUN dotnet publish apps/api/RNGWars.Api.fsproj -c Release -o /publish

FROM mcr.microsoft.com/dotnet/aspnet:10.0-noble AS api-runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* && groupadd --gid 10001 rngwars-db && useradd --uid 10001 --gid 10001 --no-create-home rngwars-db

WORKDIR /app
COPY --from=api-builder /publish .


EXPOSE 5000
ENV DOTNET_URLS=http://0.0.0.0:5000
ENV ASPNETCORE_ENVIRONMENT=Production

COPY --chmod=0555 ops/production/game-entrypoint.sh /app/game-entrypoint.sh
USER 10001:10001
ENTRYPOINT ["/app/game-entrypoint.sh"]
CMD ["dotnet", "RNGWars.Api.dll"]

FROM api-runtime AS production-prebuilt
COPY apps/frontend/dist ./wwwroot/

FROM api-runtime AS production
COPY --from=frontend-builder /app/apps/frontend/dist ./wwwroot/
