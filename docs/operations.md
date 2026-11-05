# Portable operational code and private deployment bindings

This repository is intended to own maintained application, operational and CI/CD development.
Deployment-specific values and historical operating evidence are not part of the public source. The
code here does not authorize provisioning, data access, installation, activation or recovery.

[Private deployment preparation](game-private-preflight.md) provides credential-free release
verification and a restricted read-only SSH transport probe. Neither is a mutating deployment
controller or permission to start the game. The next
[controller preparation interface](game-deployment-controller.md) independently verifies reviewed
request artifacts and immutable controller policy, but likewise performs no deployment.

## Fresh database initialization

An independently approved clean start uses the explicit offline
[`init-db <absolute-path>` command](fresh-sqlite-initialization.md) and a new private destination.
Ordinary Production startup still refuses missing, unmarked-empty or invalid storage. This
capability does not authorize deleting an existing database, reinitializing a backup repository, or
activating a service. Exact-image, storage-ownership and new-baseline off-host backup/restore gates
remain.

## Backup policy

`scripts/sqlite-backup.py` retains consistent SQLite snapshots, full schema/typed-record
verification, private files, symlink rejection, encrypted Restic backup/restore, and seven-day
hourly/thirty-day daily retention. Snapshot/verify commands operate on explicitly selected local
files. Repository operations additionally require `SQLITE_BACKUP_POLICY_FILE`, alongside the
existing repository, password-file and private-state configuration.

The policy has exactly five nonempty string fields:

| Field              | Meaning                                                                   |
| ------------------ | ------------------------------------------------------------------------- |
| `repository`       | The separately approved original repository address, not a new repository |
| `host`             | The original Restic host namespace used to select recovery points         |
| `tag`              | The original Restic tag namespace used to select recovery points          |
| `image_repository` | Exact approved GHCR image repository, without tag/digest                  |
| `data_directory`   | Absolute approved persistent data directory                               |

There are no production defaults. Changing repository/host/tag can hide prior recovery points or
change retention scope: preserve their actual approved values during migration. Do not guess them
from the public repository name. A new policy is not permission to run `init`, rotate a password,
replace credentials or create another bucket.

For an HTTPS R2 target, the policy must be a regular, singly linked **root-owned read-only file**
(mode `0400` or `0440`) in a root-owned directory (`0700` or `0750`). Its ancestors must be
root-owned and not group/world-writable; symlinks are rejected. Grant read/traverse access through
the designated backup group where needed, not world permissions. The backup process cannot rewrite
that policy. Root installation and group assignment require separate operational approval.

Disposable local repository tests instead use same-user `0600` policy files under `0700`
directories. That exception applies only to absolute local repository paths, not remote R2 policies.

The runtime repository must exactly match the policy. Namespace filters come from the policy, not
untrusted ambient environment variables. Wrong targets, missing policies, mutable remote policies,
invalid immutable image references and noncanonical data paths fail closed. Policy presence is not
proof of independently recovered credentials or a successful restore.

## Scheduler and configuration

The scheduler's `configure` command reads recovery values from stdin and requires `--policy`, a
private credentials directory and private state directory. It refuses an address that differs from
the policy and never overwrites existing credentials. No credentials belong in arguments, source,
logs or chat. `validate` requires explicit `--data-directory`, `--image` and `--policy`; it accepts
only the policy's image repository with a full lowercase SHA-256 digest and the exact data
directory.

The service file under `ops/production/backup-schedule/` is a **template**, not an installable unit.
Render its `helper_directory`, `data_directory`, `credentials_directory` and `state_directory`
bindings privately before checking/installing it. It retains UID/GID 10001, private umask, bounded
runtime, filesystem protection and hourly UTC scheduling. Local tests render and validate units;
they never install or start them.

Compose requires explicit image, loopback port and existing data directory; it never creates missing
host storage. The game USER/entrypoint and whole-directory mount are preserved. Observability is an
explicit profile with external resolver/image/project settings. No Watchtower controller is
included. Removing its source does not stop an existing updater: fence any actual old controller
separately before enabling Actions deployment. Caddy's hostname/upstream are external configuration
too.

## Infrastructure review boundary

`infra/` retains physical resource addresses and protection intent, but is a sanitized **review
candidate**, not a drop-in approved plan for existing state. Backend/account/origin/resource values
are external, repository visibility is explicit, and physical host outputs are not application
origins. No default firewall or SSH rule is supplied. Private backend and variable files are
ignored.

Cloud-init now stages root-owned configuration/helpers and inert scheduler units only. It does not
install/start a runtime, fetch credentials, join a network, start telemetry, initialize storage or
activate a service. Those old bootstrap side effects are deliberately not an implicit deployment
path. Existing hosts must not be reprovisioned with this template.

Do not apply this root until ownership of physical resources, repository objects, DNS and the backup
bucket has been reconciled. Preserve state keys/resource identities, existing names, firewall policy
and lifecycle protection under separate review; do not import, migrate, unlock or recreate resources
as a source-publication shortcut. The backup module emits a scoped credential-request template; it
does not create credentials or initialize a Restic repository.

Backend-free validation uses public provider downloads and no live credentials. It is not a real
plan, no-op proof or permission to apply. `sensitive` outputs alone do not make public deployment
logs safe: raw plans/state and detailed operational logs must stay in approved private storage.
