# Explicit offline SQLite initialization

Ordinary Production startup never creates a missing database. For an independently approved fresh
start, the API executable provides one offline command:

```sh
dotnet RNGWars.Api.dll init-db "$APPROVED_NEW_DB"
```

`APPROVED_NEW_DB` must be a new, canonical absolute file path in an existing private directory. This
command branches before construction of the web host. It ignores `DATABASE_PATH`, does not listen
for HTTP, and does not create a player or match. Its existence does not authorize a deployed reset,
deletion, storage replacement, or game activation.

## Storage contract

- Run on Linux as the non-root data owner. For the production image, that is UID/GID `10001:10001`.
  Use the image's existing entrypoint and `--init` for direct container execution.
- Prepare the separately approved destination directory as that owner with mode `0700`.
  Initialization does not create missing parent directories or change existing permissions.
- All ancestors must be real directories owned by root or the data owner. Group/world-writable
  ancestors are rejected except root-owned sticky directories such as `/tmp`. Linux `statx` must
  report the required ownership, type, mode and link metadata; unavailable metadata fails closed.
- The destination and its `-wal`, `-shm` and `-journal` siblings must not exist. Existing files,
  directories, symlinks (including dangling links) and hard-linked destinations are not replaced.
  Linked ancestors and noncanonical/relative paths are rejected.
- Use an offline, exclusively managed destination. These checks do not isolate an operator from a
  hostile root process or another process running under the same data-owner identity.

Initialization creates an owned `0700` staging directory under the destination parent. It applies
unchanged embedded migrations, verifies the schema, journal, integrity and zero population, and
marks explicit initialization. SQLite connections close before publication; the completed regular,
singly linked `0600` file has no remaining sidecars and is flushed before a no-overwrite move.
Destination and parent checks run again immediately before publication.

Only the owned staging directory is cleaned up. A killed process or machine failure can leave
private staging remnants, but a partially migrated file is not published as the destination. Inspect
any such remnants separately; do not bulk-delete existing data or treat them as a live database.
This publication safeguard is not a substitute for off-host durability and recovery verification.

Successful invocation exits `0` with `Database initialized`. Invalid argument counts exit `64`;
initialization failures exit nonzero with bounded diagnostics, without printing the destination or
exception details. Do not retry by deleting an existing destination.

## Production acceptance

The initialization marker is SQLite `application_id = 0x524E4757`. It records explicit intent, not a
credential or cryptographic authorization. Production accepts an empty database carrying this marker
only after its migration journal, schema, integrity and foreign-key checks pass. It still rejects
missing files, blank files, unmarked empty databases, incomplete journals and schema drift. Existing
populated databases without this marker retain their prior behavior.

Do not manually set the marker to bypass a refused startup. Choose a genuinely new destination and
use the initializer. The command finishes in SQLite's DELETE journal mode without sidecars; normal
startup still requires and enables WAL. Mount the entire persistent data directory, not just the
main database file. The first real anonymous signup creates the first persisted player identity; no
dummy account or Testing-mode production service is needed.

SQLite backup snapshots and encrypted Restic restore preserve the marker along with the schema,
journal and records. Test the actual approved off-host repository and restore a new baseline before
live activation. Do not reinitialize a previously configured Restic repository or rotate its
password as part of database initialization. See [operations](operations.md) for the private policy
boundary.

## Verification boundaries

Portable F# tests invoke the real executable against disposable files and invalid listening
configuration, then exercise Production storage and identity operations without an HTTP server. They
cover rejection/no-overwrite cases, unsafe ancestors, schema/journal drift, permissions and
first-user persistence. Linux tests use `/usr/bin/ln` and `/usr/bin/prlimit`.

The partial-publication test imposes a child-only file-size limit. Its test-only
`DOTNET_EnableWriteXorExecute=0` avoids exhausting that limit during CoreCLR's own memory-file
setup, so the failure reaches database creation. It changes neither normal tests nor production
runtime configuration. Core dumps are disabled in that limited subprocess.

The [native ARM64 fixture](native-game-validation.md) executes the real image's initializer, backs
up and restores that empty output through an isolated encrypted local Restic repository, and starts
Production against the restored file before the first signup and restart. No fixture result proves
live-host ownership, real off-host recovery, or deployment acceptance.
