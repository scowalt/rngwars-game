# Game deployment controller preparation

## Current boundary

`scripts/game_deploy_authority.py inspect --policy <absolute-private-policy-path>` implements the
**non-executing request-verification interface** for the future host controller. It does not install
a daemon, change SSH restrictions, reserve a deployment attempt, pull or execute an image, access a
database, restart a game, restore a backup, or grant permission to do those things.

The existing [private preflight](game-private-preflight.md) workflow still has two jobs and emits no
deployment request. This verifier deliberately rejects that workflow as deployment authority. There
is no currently enabled mutating Actions path. Source tests do not establish live GitHub
permissions, cryptographic image verification, storage readiness, or completed deployment.

## Private input and output

The caller supplies one bounded JSON envelope on stdin, with exactly `version` (integer `1`),
`run_id` (positive integer), and `github_token` (the protected job's transient read-only Actions
credential). Never pass that credential in arguments, persist it in a request artifact, or print it.
The input stream must finish within five seconds; the remaining inspection has a three-minute limit.
The credential is supplied only to GET requests through GitHub CLI in a fresh private home, with
unrelated ambient credentials removed and raw provider diagnostics suppressed.

The caller cannot select an artifact ID, image, command, target address, container name, path,
mount, environment variable, or rollback operation in this envelope. The verifier discovers the
uniquely named `game-deployment-request-<run_id>-1` artifact from GitHub, verifies its SHA-256
transport digest and source/run relationship, and parses one bounded regular `request.json` member
without extracting files. Duplicate JSON keys, extra archive members and unsafe paths are refused.
The artifact must be created and finalized between run creation and protected-job start, not
replaced afterward.

The artifact's exact fields are:

| Field                   | Meaning                                      |
| ----------------------- | -------------------------------------------- |
| `version`               | Integer `1`                                  |
| `operation`             | `deploy`; arbitrary rollback is not accepted |
| `run_id`                | The same first-attempt deployment run        |
| `controller_revision`   | Exact current main SHA                       |
| `ci_run_id`             | Fresh successful main CI for that SHA        |
| `image_source_revision` | Exact published image source SHA             |
| `image_digest`          | Full lowercase `sha256:` image digest        |
| `publication_run_id`    | Exact publication run, verified separately   |

Successful output has status `reviewed_deployment_request_verified_no_execution`, the public request
fields, and its discovered artifact ID. This is not a reusable authorization ticket: an executing
controller must independently recheck authority immediately before reserving/changing anything. The
image fields are validated identifiers here, **not proof of a genuine successful release**. The
existing release verifier must establish that proof separately, using independently trusted
verification tools and roots rather than caller-supplied trust material.

## Immutable policy

The private policy has exactly five fields: integer `version` (`1`), positive integer
`environment_id`, and full lowercase Git object IDs `workflow_blob`, `ci_blob`, and `scripts_tree`.
These pin the reviewed production environment, `.github/workflows/game-deployment.yml`,
`.github/workflows/ci.yml`, and the entire top-level `scripts` tree, respectively. Application-only
or documentation-only main commits can proceed with those same pins; controller/workflow/script
changes need a separately reviewed policy update. No untrusted request can update the pins.

The policy must be a singly linked regular read-only file (`0400` or `0440`), owned by the executing
user, under its `0700` or `0750` directory. Symlink paths, writable policies, foreign owners and
writable/untrusted ancestors are refused. This allows non-root disposable CLI tests; a future
privileged worker must additionally run as root, use root-owned installed code/policy and fixed
trusted executable paths, and never inherit an SSH caller's PATH or environment. A local CLI result
made with user-controlled tools or policy is not privileged host authority.

## GitHub authority contract

Inspection requires the exact public repository/owner identities, current main source, active manual
deployment workflow, owner actor and triggering actor, and first attempt. The main-only
`game-production` environment must retain its exact owner reviewer and no administrator bypass.
Exactly one owner approval of that environment is required.

The future workflow job inventory must contain exactly:

- `resolve`: completed successfully, producing the public request before review.
- `Private transport preflight`: skipped for a deployment operation.
- `Deploy verified game release`: currently running on `ubuntu-24.04`, started within 30 minutes.

Main CI must be successful, first-attempt, same-source, at most 24 hours old, and have its three
expected successful hosted jobs. Run/review/job state and current main are checked again after the
artifact and CI reads. Cancelled, stale, ambiguous, fork, self-hosted or unreviewed requests fail
closed. The future workflow still needs its own default-disabled mutation flag and protected gate;
these host checks do not replace them.

## Remaining execution gates

Before enabling deployment, implement and independently accept the root-worker/private-socket
adapter while retaining the unprivileged SSH account, forced command and `NoNewPrivileges`. The SSH
account must not gain sudo, Docker-group membership, a shell or backup-credential access.

Execution additionally needs selected-host/workload identity, existing storage ownership and
integrity, independent release provenance, verified encrypted recovery, isolated candidate checks, a
serialized durable attempt ledger, bounded health checks, and captured-image rollback that never
resets data. Schema-changing candidates and ambiguous interrupted attempts require explicit recovery
rather than blind retries. The already running game, ingress, backups and unrelated services must
remain protected. Installation, workflow activation and actual target acceptance are separate from
merging this preparation code.
