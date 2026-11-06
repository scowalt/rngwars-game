# Guarded game updater

The updater replaces only the captured game container with an independently verified immutable
release. It preserves the live database, ingress, backup namespace and existing administrator
access. Source availability is not installation or activation authority: the private host binding,
root-owned installation, protected workflow variable and real operational acceptance are separate.

## Protected delivery

[Automatic delivery](automatic-game-cd.md) follows successful owner main-push CI and its signed
publication. It requires trusted `GAME_AUTOMATIC_CD_ENABLED` and `GAME_DEPLOYMENT_ENABLED`
variables, not caller inputs. The main-only `game-production` environment has no per-release
reviewer in automatic mode; the approval point is the protected main merge. Manual workflow dispatch
is read-only release verification and receives no private deployment capability.

Before private access, `resolve` verifies the signed release and uploads exactly one public
`game-deployment-request-<run>-1` artifact. It contains `request.json`, with exactly `version`,
`operation`, `run_id`, `controller_revision`, `ci_run_id`, `image_source_revision`, `image_digest`,
and `publication_run_id`. These are public identifiers, never credentials or host bindings. The
exact release is recorded before execution. A single-instance replacement briefly interrupts
connections.

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
The version2 immutable policy pins the exact environment, deployment workflow blob and CI workflow
blob. It does not pin the entire scripts tree: ordinary application, documentation and test edits
can deploy while the installed root code remains unchanged. Privileged contract/controller changes
need a reviewed host policy/code update; no downloaded repository code runs as root.

The host fetches the uniquely named artifact itself and checks its SHA-256 transport digest,
source/run relationship, creation/finalization before the protected job starts, bounded regular ZIP
member and exact JSON fields. Automatic authority requires current main, successful owner main-push
CI, the exact successful automatic publisher and its receipt, first attempts and expected hosted
jobs. Run/job/main state is rechecked. Missing, stale, fork, self-hosted, duplicate or mismatched
requests fail closed. The separately supported legacy version1 contract still requires explicit
owner release review; it is not an automatic fallback.

Version2 authority policy has exactly `version` (`2`), `environment_id`, `workflow_blob` and
`ci_blob`. Legacy version1 additionally requires `scripts_tree`. Files must be singly linked,
read-only, owned by the executing user and under safe private ancestors. Non-root disposable tests
use their own policies; an installed worker requires root-owned code/policy and fixed trusted
executable paths. User-controlled CLI tools or test policies cannot confer privileged host
authority.

## Executing transaction

`game_updater.py apply --policy <absolute-private-runtime-policy>` exercises the same transaction as
the root socket worker. `status` reads its bounded outcome. The private runtime policy binds the
host/architecture, authorization policy, private state/work paths, database UID/GID/device/inode and
schema digest, backup environment, captured initial container/image, workload/network identity,
ownership label, peer IDs and bounded health timeout. There are no production target defaults.

The transaction:

1. Takes a project-only lock and independently verifies authority. Automatic requests may explicitly
   defer for an active/approaching backup before any attempt reservation or mutation. Only that
   read-only response permits a bounded caller wait/recheck, never an ambiguous response.
2. Reserves a durable, never-overwritten per-run attempt and checks actual host, captured container,
   isolation/storage, network and database. Unfinished attempts require operator recovery. The
   mutation window still excludes the last 20 minutes before the next backup; the timer is not
   stopped or replaced. Tokens are never saved.
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

Terminal outcomes are `game_deployed`, `game_rolled_back`, `deployment_blocked_before_live_change`,
or `operator_recovery_required`. Only the first is a successful deployment. `deployment_deferred` is
a distinct nonmutating response with exit75 and a bounded `retry_after_seconds`; it does not create
or consume an attempt. Preserve failed run and host receipts; do not hide a rollback behind a green
job.

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
