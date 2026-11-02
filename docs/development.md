# Local development

## Prerequisites

- Bun `1.3.11` and .NET SDK `10.0.201`, as recorded in `.mise.toml`.
- Hosted API CI explicitly uses .NET SDK `10.0.401`; do not confuse local and CI toolchain evidence.
- Node.js `24.21.0`, as declared by the marketing package.
- Restic `0.19.1` and OpenTofu `1.12.6` for portable operator tests; the separate IaC workflow
  retains OpenTofu `1.9.0`. Container stages retain their own existing tool versions.
- Python 3.14 and uv only for the comment-policy checks.
- Portless with private Tailscale sharing only when you explicitly start an HTTP server.

Keep development data disposable. Do not copy a real user database, provider token, `.env` file or
private operational configuration into this checkout. The checked-in `.env.example` files contain
only public defaults and empty analytics values. Review optional telemetry configuration before
supplying any keys. Provider-backed OAuth is not necessary for anonymous local play.

```sh
bun install --frozen-lockfile --ignore-scripts
dotnet restore apps/api.tests/RNGWars.Api.Tests.fsproj
```

Dependency lifecycle scripts are intentionally disabled for the source build. The application
package versions and lockfile are retained; do not update them silently to resolve a local problem.
The NuGet test project currently contains floating test-tool versions, so record resolved versions
when investigating differences between machines.

## A single-origin local game

The API can serve a built game client. This avoids depending on the Vite configuration's legacy
fixed-port proxy. From the repository root, build and copy the frontend into the API's ignored local
static-assets directory:

```sh
bun run --cwd apps/frontend build
mkdir -p apps/api/wwwroot
cp -R apps/frontend/dist/. apps/api/wwwroot/
cd apps/api
ASPNETCORE_ENVIRONMENT=Development DATABASE_PATH="$(mktemp -d)/game.db" SENTRY_DSN= \
  portless run --tailscale sh -c 'dotnet run --no-launch-profile -- --urls "http://127.0.0.1:$PORT"'
```

This recipe uses a new disposable database directory, not an existing database. Portless allocates
the backend port. In another terminal, use `portless list`, verify both the local and private
Tailscale endpoints it reports, and use those URLs rather than guessed ports. Do not use public
sharing or start a server when private sharing is unavailable. Stop your own temporary process when
finished; do not stop the shared proxy or another project's route. Retain or remove only the
specific disposable database directory you created.

The frontend source still contains its original Vite development defaults; this snapshot does not
claim those fixed-port defaults are suitable for a shared host. The recipe above does not exercise
Vite hot reload. HTTP/browser operation is separate from the portable build/test checks.

## Marketing development

From `apps/marketing_site`, when server use is appropriate:

```sh
portless run --tailscale sh -c 'bunx astro dev --host 127.0.0.1 --port "$PORT"'
```

The existing marketing development link points to a legacy localhost game URL; production builds use
`PUBLIC_GAME_HOST` or the public product hostname. This source-only preparation preserves that
behavior rather than silently changing routing. Verify or adapt local navigation in a separately
scoped development change. No marketing deployment command/configuration is included.

## Persistent production startup

Development/Testing mode can initialize an empty local SQLite database. Production mode cannot: it
requires an absolute persistent `DATABASE_PATH` and a compatible existing database. Do not weaken
that check, use a production credential or import player data to make a source smoke test pass.
Public operational code is documented in [operations](operations.md), but live hosting, production
initialization, backup access and deployment remain separately approved operations.
