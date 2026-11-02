# Contributing

The intended development home is this repository, with reviewed branches/PRs and GitHub Actions. Do
not maintain a parallel private development mirror or copy private operational history into a PR.

Use Bun for JavaScript dependencies and preserve the lockfile unless the change intentionally
updates dependencies. Keep functional changes separate from publication, deployment and
infrastructure ownership changes. Follow [development](docs/development.md),
[testing](docs/testing.md) and the [comment policy](.comment-policy/README.md). Required legal
notices must be retained.

Use standard Git worktrees if desired. The old fixed-port worktree helper scripts are deliberately
not included: browser-accessible local servers must use Portless with private Tailscale sharing,
allocated backend ports and verified reported endpoints. Never stop another project's service or
publish a public tunnel to resolve a local conflict.

All examples and tests must use synthetic data. Do not submit databases, state files, real `.env`
values, provider/account identifiers, private host/storage paths, production error payloads or raw
operational plans. Keep sensitive detailed evidence in an approved private channel and summarize
only the relevant non-sensitive result.

Renovate configuration remains disabled during preparation. Enabling its successor integration and
any automerge policy is a separate reviewed repository decision; copying a config file is not proof
that a bot is running or correctly scoped. No pre-commit hooks are installed automatically.

CI can build and test untrusted PR source on standard hosted runners without production credentials.
Release/CD activation requires the separate [release boundary](docs/release-boundary.md), including
controller fencing, actual source/artifact verification and appropriate owner approvals.
