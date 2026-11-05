# Guarded game updater

The updater replaces only the captured game container with an independently verified immutable
release. It preserves the live database, ingress, backup namespace and existing administrator
access. Source availability is not installation or activation authority: the private host binding,
root-owned installation, protected workflow variable and real operational acceptance are separate.

## Protected delivery

The manual `Game deployment` workflow defaults to `verify-release`. `private-preflight` still tests
transport without updating the game. The explicit `deploy` operation additionally requires the
trusted repository variable `GAME_DEPLOYMENT_ENABLED=true`; it is disabled when absent or false.
This setting is not a caller input. Both private operations use the existing main-only,
owner-reviewed `game-production` environment and the same narrowly scoped ephemeral OIDC trust.

Before review, `resolve` verifies the signed release and uploads exactly one public
`game-deployment-request-<run>-1` artifact. It contains `request.json`, with exactly `version`,
`operation`, `run_id`, `controller_revision`, `ci_run_id`, `image_source_revision`, `image_digest`,
and `publication_run_id`. These are public identifiers, never credentials or host bindings.
Reviewers see the exact release and accept the brief single-instance interruption.

The deployment job rechecks authority, verifies pinned private SSH and negative network routes, then
sends only `{version, run_id, github_token}` over private stdin to a fixed command. The token is the
job's transient read-only Actions credential. It is not a personal token, Docker credential,
argument, persisted request field or application environment variable. The owned ephemeral network
client is cleaned up even after a failed update. Public replies contain only run/source/digest and
bounded outcome fields; detailed evidence stays private on the host.

## Privilege separation

The dedicated SSH account remains unprivileged: no general shell, sudo, Docker group, forwarding,
PTY or backup-credential access. `game_ssh_dispatch.py` preserves the original read-only probe and
accepts only the exact `rngwars-game-deploy-v1` verb. Its socket path comes from the root-owned
forced command, never the SSH caller. Input and reply sizes, fields and timeouts are bounded.

`rngwars-game-updater.socket` accepts one local connection at a time, through a root-owned Unix
socket accessible only to the deployment group. The root worker checks the actual peer UID/GID,
requires the production architecture/database UID bindings, and retains `NoNewPrivileges` and
filesystem/capability restrictions. The unit file is a template: render private paths and install
only under a separately reviewed exact-target plan. The existing private SSH listener keeps its own
hardening; no public listener or network-policy expansion is needed.

The root worker explicitly retains `CAP_SETUID` during execution so it can drop to the database
account. This capability was already in its unchanged bounding set; `NoNewPrivileges` and all other
sandbox restrictions remain enabled. The database child must run as UID/GID 10001 with zero
permitted, effective and ambient capabilities. A native transient-unit canary verifies this under
the rendered worker restrictions, rather than assuming that a bounding-set entry is effective.

## Independent authority

`game_deploy_authority.py inspect --policy <absolute-private-policy>` remains a non-executing
interface. The worker calls it independently; a caller-supplied successful receipt is never enough.
The immutable policy pins the exact environment, deployment workflow blob, CI workflow blob and
entire scripts tree. Application-only commits can keep those pins; controller changes need a
reviewed host policy/code update.

The host fetches the uniquely named artifact itself and checks its SHA-256 transport digest,
source/run relationship, creation/finalization before the protected job starts, bounded regular ZIP
member and exact JSON fields. It requires owner review, current main, fresh successful same-source
CI, first attempts and the expected hosted jobs. Run/review/job/main state is checked again.
Missing, stale, fork, self-hosted, duplicate or unreviewed requests fail closed.

The authority policy has exactly `version` (`1`), `environment_id`, `workflow_blob`, `ci_blob` and
`scripts_tree`. Files must be singly linked, read-only, owned by the executing user and under safe
private ancestors. Non-root disposable tests use their own policies; an installed worker requires
root-owned code/policy and fixed trusted executable paths. User-controlled CLI tools or test
policies cannot confer privileged host authority.

## Executing transaction

`game_updater.py apply --policy <absolute-private-runtime-policy>` exercises the same transaction as
the root socket worker. `status` reads its bounded outcome. The private runtime policy binds the
host/architecture, authorization policy, private state/work paths, database UID/GID/device/inode and
schema digest, backup environment, captured initial container/image, workload/network identity,
ownership label, peer IDs and bounded health timeout. There are no production target defaults.

The transaction:

1. Takes a project-only lock and reserves a durable, never-overwritten per-run attempt. An
   unfinished attempt blocks later mutation until an operator resolves it. Tokens are never saved.
2. Checks actual host identity, the captured container and its isolation/storage, the existing
   network and database. It refuses the last 20 minutes before the next scheduled backup; the
   updater has a shorter bounded execution window, so it does not stop or replace the timer.
3. Independently fetches and verifies release provenance and exact image configuration/rootfs. No
   image is selected by tag, caller command, arbitrary path or caller-supplied trust root.
4. Uses the database account to make an encrypted recovery point, restore it separately and compare
   all schema, journal and typed records. No init, retention, prune or live-data replacement occurs.
5. Runs an isolated candidate against a copy with no public ports or external network. Schema,
   migration-journal and record changes at startup are refused before the live game is stopped.
6. Rechecks authority, creates the future container, stops only the captured previous container and
   records the frozen database identity/content. The new game starts without the ingress alias.
7. Checks health and unchanged persisted data, then activates the existing network alias and records
   the new current container. The previous container/image remains available, stopped.

On a known health failure, rollback may stop the failed container and restart only the captured
previous one, after proving the database is still unchanged and compatible. It never restores a
backup automatically. Changed data, unclear Docker mutations, interrupted attempts or unsafe state
require operator recovery, not a guessed rollback or a blind retry. A durable attempt cannot be
replayed even if the hosted job lost its connection.

Outcomes are `game_deployed`, `game_rolled_back`, `deployment_blocked_before_live_change`, or
`operator_recovery_required`. Only the first is a successful deployment. Preserve failed run and
host receipts; do not hide a rollback behind a green job.

## Verification and activation

Portable tests exercise real files, SQLite and encrypted local Restic recovery. External
GitHub/registry/Docker transports have doubles for fault injection. A separate ARM64 hosted fixture
uses real containers, the actual private-socket peer boundary, the unprivileged SSH adapter, data
persistence and captured rollback. Its GitHub/registry transports are explicitly synthetic; it does
not claim live authorization or image cryptography.

Actual protected hosted acceptance on the selected host must independently establish genuine release
verification, token permissions, ephemeral network cleanup, Linux ownership, encrypted recovery and
update/rollback behavior. Install verified project-local tools and root-owned policies first, keep
deployment disabled until the reviewed controls pass, and preserve the live game and all prior
recovery points/history throughout. Merging this source alone does not enable CD.
