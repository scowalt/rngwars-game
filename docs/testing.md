# Test coverage and CI boundaries

## Portable checks

Run the commands in the root README. Backend tests use synthetic/disposable SQLite data and test
native schema handling, storage and ELO behavior. Frontend tests run through Vitest; marketing
validation and builds do not start an HTTP server.

```sh
dotnet test apps/api.tests/RNGWars.Api.Tests.fsproj --no-build --no-restore --filter 'FullyQualifiedName!~ApiHttpTests'
uv run --no-project --python 3.14 --with-requirements .comment-policy/requirements.txt python .comment-policy/check.py
uv run --no-project --python 3.14 --with-requirements .comment-policy/requirements.txt python -m unittest discover -s .comment-policy -p 'test_*.py'
```

The comment-policy checker expects a Git checkout. See its [guide](../.comment-policy/README.md).
Legal notices must be retained even where normal source comments are prohibited.

## HTTP fixtures are separate

`ApiHttpTests` starts real temporary API processes through Portless/private Tailscale using an
isolated synthetic database. Its source is retained, but the default portable command and hosted CI
exclude it. Running unfiltered `dotnet test` would include these fixtures.

Only run them when explicitly permitted to create private test routes and when Portless/Tailscale is
available. Use disposable data, verify the reported local/private URLs, and confirm cleanup. Do not
substitute a public tunnel, a hard-coded shared port or production data. A portable test pass is not
HTTP coverage.

## Hosted CI design

The source workflows use standard GitHub-hosted runners, full-SHA action references, read-only
repository permissions and checkouts without persisted credentials. They contain no repository
secret references, deployment/image-publication steps, private-runner labels or privileged
`pull_request_target` / `workflow_run` entry points. API/frontend checks run on main, release and
production PRs/pushes without path filters that could strand required promotion checks.

Frontend build telemetry is disabled by empty values. Portable ops CI runs script/operator tests
against disposable synthetic data and local encrypted repositories; tests render scheduler units and
parse Compose without a daemon. IaC CI initializes with `-backend=false`, validates and lints
without live credentials. Container CI builds a non-published image, treats HIGH/CRITICAL
vulnerability findings as advisory and uploads SARIF; build/scanner errors or missing artifacts
still fail. Container/Checkov/hosted execution is not implied by local configuration validation.

```sh
python3 -W default::ResourceWarning -m unittest discover -s scripts/tests -v
uv run --no-project --python 3.14 --with-requirements ops/tests/requirements.txt python -W default::ResourceWarning -m unittest discover -s ops/tests -v
```

Operator tests require Restic and OpenTofu; configuration tests also use Docker's CLI as a parser
and `systemd-analyze verify`, never a running container or installed unit. Public provider-package
retrieval is not a plan/apply or authenticated cloud operation. Release-guard tests use fake
evidence and never publish/deploy. Fork approval, artifact retention and branch protection remain
explicit repository-owner settings, not assertions made by a workflow file.

A successful local check does not establish a hosted Actions pass or satisfy all branch-protection
requirements. Check workflow runs for the exact candidate SHA, and assess non-Actions protection
requirements separately. Do not re-enable an old publisher to make build status green.
