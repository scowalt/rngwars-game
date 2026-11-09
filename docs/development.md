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

## Styling

Both web apps use plain CSS with cascade layers and no CSS framework. Each global stylesheet
declares `@layer theme, base, components;` once: `theme` holds design tokens as custom properties,
`base` is a small reset, and `components` holds named semantic classes. The game client's styles
live in `apps/frontend/src/styles/` and are imported by `src/index.css`; the marketing site's live
in `apps/marketing_site/src/styles/global.css`. Add a semantic class rather than utility classes,
and use plain conditional class names instead of a class-merging helper. Stylesheets fall under the
comment policy, so record any rationale in documentation rather than CSS comments.

## OAuth sign-in

The game client has no sign-in button yet. A client signs in through three same-origin requests.

1. `POST /auth/{provider}` with the anonymous token, if any, in the `Authorization: Bearer` header.
   The response is `{ "url": "<provider authorize URL>" }` and an HttpOnly flow cookie. Navigate the
   browser to `url`.
2. The provider redirects to `/auth/{provider}/callback`. The API accepts the callback only from
   the browser that holds the flow cookie, with the matching `state`, within 10 minutes and once.
   It then redirects to `/auth/success`, or to `/?auth_error=OAUTH_ERROR` on any failure.
3. From `/auth/success`, `POST /auth/session` within one minute. The response has the same
   `{ token, user }` shape as anonymous signup and clears the flow cookie.

The anonymous token never appears in a URL. The flow cookie is `__Host-` prefixed, so it is always
`Secure`. Browsers keep it over HTTPS, and Chromium and Firefox also keep it on plain-HTTP
`localhost`. Other plain-HTTP origins cannot complete sign-in. The Vite development server proxies
only `/api` and `/hubs`, so a client that uses it also needs an `/auth` proxy entry.

Pending flows are held in API memory, so a restart cancels them and the player signs in again. At
most 10,000 flows can be pending. When the limit is reached, `POST /auth/{provider}` returns 503
`SIGN_IN_BUSY` until enough flows expire.

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
