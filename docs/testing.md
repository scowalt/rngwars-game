# Test coverage and CI boundaries

## Portable checks

Run the commands in the root README. Backend tests use synthetic/disposable SQLite data and test
native schema handling, storage and ELO behavior. Linux backend tests also invoke the real offline
initializer, exercise first-player Production persistence and reject unsafe/partial storage; see the
[initialization contract and fault-injection boundary](fresh-sqlite-initialization.md). Frontend
tests run through Vitest; marketing validation and builds do not start an HTTP server.

```sh
dotnet test apps/api.tests/RNGWars.Api.Tests.fsproj --no-build --no-restore --filter 'FullyQualifiedName!~ApiHttpTests'
uv run --no-project --python 3.14 --with-requirements .comment-policy/requirements.txt python .comment-policy/check.py
uv run --no-project --python 3.14 --with-requirements .comment-policy/requirements.txt python -m unittest discover -s .comment-policy -p 'test_*.py'
```

The comment-policy checker expects a Git checkout. See its [guide](../.comment-policy/README.md).
Legal notices must be retained even where normal source comments are prohibited.

## Anonymous signup coverage

Three layers cover anonymous signup, and only the first two run in the portable command.

- `DatabaseTests` exercise `Database.createAnonymousUser` and `getUserByToken` directly.
- `AnonymousSignupRouteTests` run the real Giraffe route table in process against a disposable
  native SQLite file, with no listener. They cover the token roundtrip, 32 concurrent signups, and
  the `SIGNUP_FAILED` response for a rejected insert, a row that vanishes before it is read, and
  storage that disappeared. Fault cases use SQLite triggers on the synthetic database and check that
  no token or storage detail reaches the response. The vanished-row case also checks that the insert
  ran once and was not retried.
- `ApiHttpTests` repeat concurrent signup and a rejected insert over real HTTP. They are excluded
  from the portable command and hosted CI, as described below.

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
parse Compose without a daemon. The separate hosted native ARM64 workflow runs the actual image's
offline initializer, encrypted local backup/restore and first-user Production restart checks in
network-isolated containers. It does not access a live host or real backup repository. IaC CI
initializes with `-backend=false`, validates and lints without live credentials. Container CI builds
a non-published image, treats HIGH/CRITICAL vulnerability findings as advisory and uploads SARIF;
build/scanner errors or missing artifacts still fail. Container/Checkov/hosted execution is not
implied by local configuration validation.

### Container diagnostics

The Docker build step sets `DOCKER_BUILD_SUMMARY` and `DOCKER_BUILD_RECORD_UPLOAD` to `"false"`.
This disables its optional build summary and downloadable `.dockerbuild` record, avoiding retention
of detailed build traces. Normal build logs, metadata output and build-check annotations remain; the
image build, vulnerability scan and explicit Trivy SARIF upload are unchanged.

These settings apply to this workflow definition, not all repository diagnostics. They do not delete
existing artifacts or change repository visibility, artifact access or retention. Historical refs
and other workflows can retain different settings. Review future workflow changes accordingly;
ordinary CI logs still disclose runner, tool and build metadata.

### Checkov visibility contract

The Checkov step evaluates a **synthetic private configuration** using
`.github/checkov/private-repository.tfvars`. This supplies only `repository_visibility = "private"`
to the scanner through its `var_file` input. It is outside `infra/`, is not automatically loaded by
Terraform/OpenTofu, and must not be used as a deployment binding. This one fixture is intentionally
tracked; the general `*.tfvars` ignore rule still protects private bindings. The real visibility
variable remains required with no default; the privacy check and existing exclusions are unchanged.

This fixture tests the reusable template, not live GitHub settings. A passing scan does not
establish that any deployed repository is private, authorize public visibility, or replace review of
real bindings and infrastructure state. Intentional public publication remains a separate decision.

The regression script drives the actual Checkov CLI using the workflow's scanner inputs. It verifies
private configuration succeeds, while public input, absent input, and a literal public resource
despite the private fixture fail specifically `CKV_GIT_1`. It also guards against new skip/soft-fail
controls. Only tracked infrastructure inputs are copied into temporary test cases; ignored state,
untracked private variable files and provider caches are not test inputs, and the source files
remain unchanged.

With Git and Checkov installed in the same Python environment, run:

```sh
uv run --no-project --python 3.12 --with checkov==3.4.0 python .github/checkov/test_visibility.py -v
```

The tests use an isolated home and environment, disable scanner metadata downloads, and do not run
Terraform/OpenTofu, contact providers, or operate on live infrastructure. In GitHub Actions, they
run in the existing Checkov image after the scan, with no network and a read-only workspace mount.
The container must already be present (`--pull=never`), so the tests reuse the scan's tool image.
Keep the regression image tag aligned with the image used by the pinned Checkov action when
reviewing future tool updates.

### Portable operator checks

```sh
python3 -W default::ResourceWarning -m unittest discover -s scripts/tests -v
uv run --no-project --python 3.14 --with-requirements ops/tests/requirements.txt python -W default::ResourceWarning -m unittest discover -s ops/tests -v
```

Operator tests require Restic, OpenTofu and the OpenSSH server/client CLIs. Configuration tests use
Docker's CLI as a parser, `systemd-analyze verify` and `sshd -T`, never a running container,
listener or installed unit. Release-verifier tests exercise real files with external CLI/provider
doubles; restricted SSH probe tests exercise stdin, terminal rejection and timeouts without starting
SSH. See [private deployment preparation](game-private-preflight.md) for the distinction between
these interfaces and actual authenticated deployment. Public provider-package retrieval is not a
plan/apply or authenticated cloud operation. Release-guard tests use fake evidence and never
publish/deploy. Fork approval, artifact retention and branch protection remain explicit
repository-owner settings, not assertions made by a workflow file.

A successful local check does not establish a hosted Actions pass or satisfy all branch-protection
requirements. Check workflow runs for the exact candidate SHA, and assess non-Actions protection
requirements separately. Do not re-enable an old publisher to make build status green.
