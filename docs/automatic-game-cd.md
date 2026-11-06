# Automatic game delivery from protected main

## Approval happens at merge

The game delivery chain is:

```text
owner push to protected main
  successful first-attempt CI
  isolated native image build and validation
  immutable publication and genuine source attestation
  independently verified publication receipt
  private OIDC/SSH -> guarded host updater
  recovery -> private candidate -> health/data checks -> live game
```

Public visibility does not grant write or merge permission. At activation, the owner is the sole
listed collaborator. Main requires a PR, resolved conversations and strict successful API, frontend
and portable-operations checks, including administrator enforcement; force pushes and deletion
remain forbidden. The sole maintainer can merge their own PR without an impossible self-approval
requirement. Ordinary Actions tokens cannot approve PRs and stay read-only.

The game publication/production environments retain main-only branch restrictions and no admin
bypass, but automatic mode expects no per-release reviewer gate. Marketing gates are unchanged.
Adding another writer or changing privileged workflow/host policy is a separate trust decision.

## Triggers and exact lineage

`Game image publication` follows successful `CI` completion only for an owner main **push** in this
repository. `Game deployment` follows a successful automatic game publication. There are no path
filters on these automatic triggers: ordinary main pushes are eligible even when they only change
documentation or tests. PR/fork, feature-branch, manual-CI, failed/cancelled and rerun events do not
confer automatic release authority.

Event payloads are selectors, not trusted proof. The scripts independently fetch workflow/run/job
metadata and validate repository/head-repository IDs, owner and triggering actor, current main,
first attempts, fresh same-source push CI and exact hosted jobs. The deployment resolver discovers
the unique bounded publication receipt, verifies its artifact digest and source/run binding, then
verifies the actual signed image. It derives the deployment inputs; callers cannot choose an older
image or another repository's artifact.

An obsolete queued revision is skipped or refused before publication/deployment. Publication that
has already happened is still verified and finalized if main advances. A running host transaction is
never cancelled to make room for a newer push. This prevents older queued work overwriting a newer
release while preserving safe completion of work already authorized.

Manual workflow dispatch remains available for **read-only** candidate/release verification. It does
not publish or receive private deployment secrets. Administrative recovery remains separate from
automatic delivery; there is no automatic PR merge or general remote shell.

## Enablement and private identity

Automatic execution additionally requires the trusted repository variable
`GAME_AUTOMATIC_CD_ENABLED=true`, plus the existing `GAME_PUBLICATION_ENABLED` and
`GAME_DEPLOYMENT_ENABLED` switches for their respective stages. Missing/false switches prevent new
automatic starts. They are not dispatch inputs. Disable automation before changing its installed
contract; do not interrupt a transaction already mutating the game.

The exact existing Tailscale trust selects `workflow_run` for the deployment workflow. Its issuer,
immutable owner/repository/environment subject, repository and owner IDs, main ref, workflow path,
owner actor, dedicated tag, scopes and private network grant remain restricted. Do not replace this
with a wildcard, long-lived network token or personal administrator key.

Only the private deployment job receives the existing environment-scoped network binding and
restricted SSH key. Source-build jobs do not receive registry-write or private-network capability.
The host still verifies the transient read-only job credential against provider metadata; it never
trusts a caller's claimed successful verification.

## Host policy and safe waiting

Host authority policy version2 has exactly `version` (`2`), `environment_id`, `workflow_blob` and
`ci_blob`. It pins the privileged workflow/CI contract but no longer pins the entire scripts tree.
Application, documentation and ordinary test/script edits can therefore flow without silently
installing new privileged code. Installed worker code and host/storage policy remain immutable;
workflow/CI contract or incompatible controller changes still need reviewed installation/pin
updates. Version1 is a separately validated legacy manual-review contract, not an automatic
fallback.

The updater checks backup readiness **before reserving an attempt or mutating anything**. An active
backup or approaching backup window returns `deployment_deferred` with a bounded wait interval. The
caller may wait and recheck authority only for that explicit read-only response. It never retries a
transport error, missing reply, consumed attempt or uncertain mutation. Wait time is bounded; the
worker's mutation budget is unchanged. Broken backup state blocks rather than waits forever. A newer
main revision while waiting invalidates the old request.

The [guarded updater](game-deployment-controller.md) still verifies genuine image identity, existing
storage, encrypted recovery, a private candidate, health and preserved data. Captured-image rollback
never restores the database automatically. Unexpected state or an interrupted mutation requires an
operator. Failed attempts and outcomes remain recorded.

## Acceptance, not just configuration

Changing YAML or removing reviewer settings is not proof of automatic CD. Cutover must verify the
new source and denied cases, install the exact host policy/code, update only the required OIDC
claim, and enable the automatic switch deliberately. A real later main push must traverse CI,
publication and deployment without a manual dispatch or approval. Independently compare its
artifacts and source identities with the live image, preserved player data, verified recovery and
owned ephemeral-node cleanup. Keep the healthy live game and all prior recovery/history intact
throughout cutover; leave automation disabled if a trust or verification dependency is blocked.
