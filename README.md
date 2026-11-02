# RNGWars

A satirical multiplayer web game where the only skill is your random number.

- **API:** F# / .NET 10, Giraffe, SignalR and SQLite.
- **Game client:** SolidJS, Vite and Tailwind CSS.
- **Marketing site:** Astro and SolidJS.

This tree is being prepared as the authoritative home for RNGWars development, CI and CD on GitHub
Actions. It contains application and maintained operational code, but no player database, private
operational history, infrastructure state or deployment credentials. CI source and release
preparation are not authorization to publish an image or activate a deployer. Public product links
do not establish current service availability.

## Build and test

Use the runtime versions in `.mise.toml`; the marketing package also declares its Node.js version.
Use Bun rather than npm or Yarn. See [development](docs/development.md) for isolated local setup and
[testing](docs/testing.md) for the exact coverage boundary.

```sh
bun install --frozen-lockfile --ignore-scripts
bun run --cwd apps/frontend test
bun run --cwd apps/frontend build
bun run --cwd apps/marketing_site check
bun run build:marketing

dotnet restore apps/api.tests/RNGWars.Api.Tests.fsproj
dotnet build apps/api.tests/RNGWars.Api.Tests.fsproj --no-restore --warnaserror
dotnet test apps/api.tests/RNGWars.Api.Tests.fsproj --no-build --no-restore --filter 'FullyQualifiedName!~ApiHttpTests'
```

No production credentials are needed. Leave `VITE_POSTHOG_KEY`, `PUBLIC_POSTHOG_KEY`,
`VITE_SENTRY_DSN` and `SENTRY_DSN` unset or empty to disable analytics/error reporting.

The default portable test command deliberately excludes HTTP fixtures. Passing it does not prove
HTTP, browser, container or deployed-service behavior.

## Source layout

| Path                   | Contents                                                                                |
| ---------------------- | --------------------------------------------------------------------------------------- |
| `apps/api/`            | API, game actors, authentication and schema migrations                                  |
| `apps/api.tests/`      | Synthetic database/game tests and separately gated HTTP fixtures                        |
| `apps/frontend/`       | Game client                                                                             |
| `apps/marketing_site/` | Marketing site source, without deployment configuration                                 |
| `scripts/`, `ops/`     | Backup/transfer helpers, policy validation, synthetic tests and configuration templates |
| `infra/`               | Parameterized infrastructure definitions; backend-free validation only                  |
| `.github/workflows/`   | Hosted application/ops/IaC/container CI; release activation remains gated               |
| `.comment-policy/`     | Self-contained source policy checker and tests                                          |

The Dockerfile and its generic entrypoint are included as build inputs only. They do not grant
access to an existing database or make a fresh Production database safe to initialize. Production
startup intentionally requires an existing compatible persistent SQLite database.

## License

Owner-controlled original code and documentation are available under the [MIT license](LICENSE).
Dependencies retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md). The
marketing favicon is an original geometric die drawing, not a third-party framework logo.

## Publication boundary

CI runs application and synthetic operational checks, backend-free infrastructure validation and a
non-publishing container scan. It has no production secrets or private runners. Actual publication
and deployment must move to reviewed GitHub Actions controllers through a deliberate cutover—not by
enabling an old workflow or leaving duplicate publishers active.

See [operational contracts](docs/operations.md) and the
[release boundary](docs/release-boundary.md). The current candidate has no active CD jobs; that is a
preparation gate, not the final architecture.
