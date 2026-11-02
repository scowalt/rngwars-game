# GitHub Actions release and migration boundary

The intended end state is one authoritative public development repository with CI and CD owned by
GitHub Actions. The current preparation includes portable tooling, CI source and a tested context
guard. No publisher/deployer is enabled until the project-specific controller cutover is approved.

## Context guard is not a publisher

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

The future controller must independently verify original evidence identity and integrity, registry
state, source/native architecture and reviewer/environment authorization before using the guard. The
current tests exercise rejection/validation contracts with synthetic evidence; they are not release
acceptance. Missing proof remains a blocker, not permission to fabricate `passed` values.

## No second routine publisher

The former manual registry publisher is not exported. Its private source and historical verification
records remain preserved. The successor guard tests retain owner/repository/ref/revision, freshness,
missing/tampered evidence, no-overwrite/no-retry, architecture and digest-approval intent. This does
not claim every original publisher behavior is implemented in a new controller; the actual publish,
verification-evidence adapter and deployment implementations require review and real gated tests.

Game image publication and deployment are separate authorizations. Keep immutable full-SHA tags and
full digest identity; no automatic `latest` updater. Selecting a native runner does not prove a
native image until the resulting manifest/config and actual build execution are verified. An
intentionally dormant game does not need to be restarted just to move source and CI.

## Controlled cutover

For marketing, game publishing and game deployment independently:

1. Approve the canonical repository, protected environment/branch policy and exact controller
   source.
2. Verify minimal credential/package/network access without exposing values. Public forks receive no
   private-runner, publishing, hosting, production or backup capabilities.
3. Verify the old project-specific trigger is fenced before the replacement can act. Do not stop a
   shared CI service or leave two release paths active.
4. Approve the exact revision/artifact and, for game deployment, the exact digest and current
   recovery gates. Preserve live data, backup identity and rollback authority.
5. Retain private detailed evidence, emit only bounded non-sensitive status, and preserve real
   command exit/failure semantics. Raw provider plans, host details, credentials and databases must
   not become public Actions artifacts.
6. Verify the approved live operation and retire the replaced trigger only within the authorized
   sequence. Fresh public Actions results and owner acceptance are required before calling the
   development/CI/CD migration complete.

Do not make private history public to transfer tasks. Recreate sanitized current issues/PRs,
preserve a private mapping, and port unmerged application changes through review instead of
importing old storage implementations or deployment exceptions wholesale.
