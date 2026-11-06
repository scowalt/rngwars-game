# Protected native game image publication

`Game image publication` separates source builds, candidate verification, registry writes and
provenance. It never deploys the game, opens a host port, reads a real database or receives a host,
backup or tailnet credential. Registry publication is not deployment acceptance.

## Automatic invocation

The workflow follows successful first-attempt owner **push CI on main** in this repository. All
three CI jobs must succeed. It independently rechecks branch/ref, repository/head-repository IDs,
workflow identity, owner/triggering actor, exact source and CI freshness against GitHub metadata.
PR/fork, feature-branch, manual-CI and failed or rerun contexts do not authorize publication.

The main-only `game-publication` environment has no per-release reviewer in automatic mode and no
admin bypass. Both `GAME_AUTOMATIC_CD_ENABLED=true` and `GAME_PUBLICATION_ENABLED=true` are required
from trusted repository variables, not user inputs. The existing immutable release-attempt ruleset
must still prohibit update/deletion bypass. The approval point is the owner's protected main merge;
see [automatic delivery](automatic-game-cd.md).

Owner-only manual dispatch retains `validate`, which builds/verifies a candidate without publishing
or signing. Automatic source and controller revisions must still be current before publication;
obsolete queued revisions are skipped or refused. The publisher rechecks the exact manifest and
archive after independently downloading the native artifact. Once a publication has happened, its
verification may finish even if main advances, so an already reserved attempt is not abandoned or
replayed. Disabling a switch prevents later starts; it does not cancel an active publication.

Host identity, fencing, storage and real encrypted recovery remain separately verified by the
updater. A caller-supplied recovery boolean is never treated as operational evidence.

## Build and artifact isolation

The native build job runs on GitHub-hosted `ubuntu-24.04-arm` with read-only repository permission.
It has no registry-write, signing, hosting or backup capability. It builds the actual `production`
Docker target as OCI, imports it into the disposable Docker daemon and runs the existing native
fixture. Frontend telemetry build arguments are empty for this private-verification image; public
activation/configuration acceptance remains separate.

The OCI config digest must equal the local image ID exercised by the native fixture. The fixture
checks offline initialization, encrypted local recovery, Production first signup/restart and
negative storage cases, with no published ports or external container network. Its database is not
uploaded. Only `image.oci.tar` and the bounded native JSON receipt enter the candidate artifact.
Optional Docker build records/summaries and BuildKit attestations are disabled; the later trusted
job signs the exact published image instead.

`scripts/game_artifact.py` exposes `inspect` and `verify-native`. It bounds the archive to 1GiB, 128
entries, metadata documents to 2MiB and layers to 64. It permits one image, optionally behind one
single-platform OCI index wrapper. Digests and sizes bind every referenced manifest/config/layer;
unknown payloads, duplicate archive/JSON entries, external descriptors, unexpected source/runtime,
other architectures and trailing data are rejected. It reads archive members but never extracts or
executes their contents. Native receipt consistency is explicitly **not release approval**.

The trusted `prepare` job checks the actual successful hosted ARM build job, artifact/run/repository
identity and transport digest, then revalidates OCI and native receipt identity. It creates only a
new private output directory; it does not overwrite another candidate.

## Registry and provenance

Only the main-authorized publication job receives the successor's `GITHUB_TOKEN` with package-write,
attestation-write, contents-write and OIDC permissions. Contents-write reserves an immutable
`release-attempt/game-publication/<full-source-SHA>` tag before image upload. No historical package
access or owner-wide package credential is granted to this repository.

GitHub hides the ruleset's bypass-actor list from callers without ruleset-write access. The workflow
never interprets an omitted list as empty: when it is hidden, the effective
`current_user_can_bypass` value must explicitly be `never`. Visible exceptions, any effective
bypass, or absence of both forms of evidence block reservation. The owner-side full-policy check
remains separate; this avoids granting policy administration to the publishing token. Attempt and
receipt metadata state which visibility path was checked. Unexpected local/provider failures report
only a bounded stage and exception class, never exception values or raw diagnostics.

The sole destination is `ghcr.io/scowalt/rngwars-game-releases:<full-source-SHA>`. Existing registry
tags or attempt reservations block publication. A failed/ambiguous operation is not retried or
cleaned away; inspect its actual registry/ledger state privately. Full-SHA tags are protected by
this controller's policy, not a claim that registry administrators cannot change them. Consumers
must use an exact digest.

Skopeo copies the validated OCI image with explicit native-platform selection and digest
preservation. It receives a private authentication-file path, not credentials on argv. Custom
registry metadata requests use bounded captured output and do not follow redirects with credentials.
The resulting manifest digest and config reference are checked before signing. The pinned
attestation SDK reads `HOME/.docker/config.json`, while registry tools also support `DOCKER_CONFIG`.
A fresh private signing home aligns both paths; only the signing action receives that HOME override.
The runner's default Docker configuration is untouched. Always-run cleanup checks the owned home's
marker/permissions before removing it; credentials never enter publication artifacts.

The pinned GitHub attestation action signs the published digest and stores genuine provenance in the
registry. Its optional storage record and summary are disabled. Verification invokes the actual
`gh attestation verify` protocol against registry attestations, requiring the exact trusted
workflow, GitHub issuer, signer/source revision, main ref, hosted runner, SLSA predicate, image
digest and this run's first invocation. A matching digest or unverified JSON alone does not pass.

## Acceptance boundaries

Portable tests use real CLI/file behavior and external tool/provider doubles. They do not prove
registry permissions, a hosted build, signatures or production readiness. Actual protected workflow
execution and independent registry/provenance verification are required before accepting
publication. A successful automatic publication triggers the separate guarded deployment workflow,
which must independently verify the complete chain and host safety; the publisher itself has no host
capability. See [automatic delivery](automatic-game-cd.md),
[release boundaries](release-boundary.md) and [native validation](native-game-validation.md).
