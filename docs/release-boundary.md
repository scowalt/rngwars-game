# GitHub Actions release and migration boundary

The intended end state is one authoritative public development repository with CI and CD owned by
GitHub Actions. [Marketing releases](marketing-release.md) have a separate protected controller.
[Automatic game delivery](automatic-game-cd.md) follows protected owner-main merges through CI,
[isolated signed publication](game-image-publication.md) and the guarded updater. Manual dispatch
only validates; enabling automation still requires explicit controller, identity and live-acceptance
cutover. Publication and host mutation remain separate jobs and capabilities.

## Legacy context guard is not a publisher

This preparation-era contract is not the automatic game's authorization adapter.
`scripts/release_gate.py` has no network, registry or deployment implementation. It validates an
explicit policy, GitHub execution context, freshness/completeness metadata and an artifact's actual
SHA-256. It reports **context validated only; no operation performed**. It does not authenticate
arbitrary evidence, prove an external controller stopped, verify a hosted check result, or establish
live recoverability. A boolean attestation is not external-state proof.

Policy must explicitly bind repository name and numeric ID, owner and rerun actor, protected ref,
reviewed environment, enabled operation, image repository, native platform and required checks.
Manual dispatch, exact full approved SHA, first attempt, current evidence, and a private fence
reference are required. Publication rejects existing tags; game deployment additionally requires
separate exact published-digest approval and completed recovery evidence. Marketing requires
approval of the exact built-asset hash. All of these fields must come from trusted, reviewed
workflow and evidence adapters, never unchecked PR inputs or a caller-written claim of successful
checks.

An actual controller must independently verify original evidence identity and integrity, registry
state, source/native architecture and reviewer/environment authorization. The context guard's tests
exercise rejection/validation contracts with synthetic evidence; they are not release acceptance.
The game publication adapter separately checks actual GitHub metadata, native OCI identity,
main-push/environment authority and registry provenance; its synthetic provider tests still require
real protected publication/readback before operational acceptance. Missing proof remains a blocker,
not permission to fabricate `passed` values.

## No second routine publisher

The former manual registry publisher is not exported. Its private source and historical verification
records remain preserved. The successor guard tests retain owner/repository/ref/revision, freshness,
missing/tampered evidence, no-overwrite/no-retry, architecture and digest-approval intent. This does
not by itself implement registry writes. The separate game publication workflow and adapter require
real gated execution and provenance readback; a deployment controller remains a distinct capability.

Game image publication and deployment are separate authorizations. Keep immutable full-SHA tags and
full digest identity; no automatic `latest` updater. Selecting a native runner does not prove a
native image until the resulting manifest/config and actual build execution are verified. An
existing game must not be restarted by source-only validation.

## Controlled cutover

For marketing, game publishing and game deployment independently:

1. Approve the canonical repository, protected environment/branch policy and exact controller
   source.
2. Verify minimal credential/package/network access without exposing values. Public forks receive no
   private-runner, publishing, hosting, production or backup capabilities.
3. Verify the old project-specific trigger is fenced before the replacement can act. Do not stop a
   shared CI service or leave two release paths active.
4. Establish the exact approval point: marketing retains artifact review; automatic game delivery
   uses protected-main merge authority and independent exact-image/recovery verification. Preserve
   live data, backup identity and rollback authority.
5. Retain private detailed evidence, emit only bounded non-sensitive status, and preserve real
   command exit/failure semantics. Raw provider plans, host details, credentials and databases must
   not become public Actions artifacts.
6. Verify the approved live operation and retire the replaced trigger only within the authorized
   sequence. Fresh public Actions results and owner acceptance are required before calling the
   development/CI/CD migration complete.

Do not make private history public to transfer tasks. Recreate sanitized current issues/PRs,
preserve a private mapping, and port unmerged application changes through review instead of
importing old storage implementations or deployment exceptions wholesale.
