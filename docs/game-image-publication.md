# Protected native game image publication

`Game image publication` separates source builds, candidate verification, registry writes and
provenance. It never deploys the game, opens a host port, reads a real database or receives a host,
backup or tailnet credential. Registry publication is not deployment acceptance.

## Invocation and review

The workflow supports owner-only `workflow_dispatch` on current `main`, first attempt only. Inputs
are the exact approved revision, a successful current-main CI run ID from the last 24 hours, and
`operation` (`validate` by default, or `publish`). All three existing CI jobs must have succeeded.
Branch/ref, repository/owner IDs, workflow identity, actual run actor and triggering actor are
checked against GitHub metadata, not only environment strings.

`validate` builds and verifies a candidate without requesting publication or signing privileges.
`publish` also enters the separately configured `game-publication` environment. Before dispatching
publication, the owner must configure that environment with:

- A main-only custom branch policy, exactly the owner reviewer, self-review permitted for the single
  maintainer, and no admin bypass.
- Repository variable `GAME_PUBLICATION_ENABLED=true`. Absence or any other value blocks publishing.
- The existing immutable release-attempt ruleset, with no update/deletion bypass. The owner checks
  the complete management view immediately before approving each candidate.

For a publication request, `resolve` checks the enablement and preexisting protected environment
before the privileged job can be scheduled. Enablement is supplied by GitHub's repository `vars`
context, not a dispatch input or a Variables-management API token. The publisher checks that
injected value and rereads environment/branch policies and this run's actual review history after
the gate. Disabling the variable gates later jobs/dispatches; it does not cancel a job already
executing. A missing, rejected, wrong-user or ambiguous review blocks registry writes. Source and
controller revision must still be current. Review the source, manifest digest and archive digest
shown by `prepare`; the publisher rechecks both digests after downloading the artifact again.
Private target ownership, controller fencing and real recovery evidence remain owner acceptance
gates outside the public workflow. The workflow does not turn a caller-supplied recovery boolean
into operational evidence.

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

Only the reviewed publication job receives the successor's `GITHUB_TOKEN` with package-write,
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
The resulting manifest digest and config reference are checked before signing. The owned
authentication file is removed by the workflow's always-run cleanup; credentials never enter
publication artifacts.

The pinned GitHub attestation action signs the published digest and stores genuine provenance in the
registry. Its optional storage record and summary are disabled. Verification invokes the actual
`gh attestation verify` protocol against registry attestations, requiring the exact trusted
workflow, GitHub issuer, signer/source revision, main ref, hosted runner, SLSA predicate, image
digest and this run's first invocation. A matching digest or unverified JSON alone does not pass.

## Acceptance boundaries

Portable tests use real CLI/file behavior and external tool/provider doubles. They do not prove
registry permissions, a hosted build, signatures or production readiness. Actual protected workflow
execution and independent registry/provenance verification are required before accepting
publication. No real game deployment or database operation follows automatically. See
[release boundaries](release-boundary.md) and [native validation](native-game-validation.md).
