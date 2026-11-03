# Development and automation routing

New source work, issues and pull requests belong in `scowalt/rngwars-game`. Start new work from its
protected `main`; do not transplant historical branches, operational evidence, databases or private
issue discussions into this repository. The migration tracker is issue #10. Existing historical work
is preserved separately and is not completed merely by opening a successor issue.

## Dependency updates

Renovate remains deliberately paused (`enabled: false`). Migration does not silently resume a
previously paused automation or change an account-wide App installation. When separately enabled,
this repository's configuration is the destination, with the existing schedule and two-per-hour /
three-concurrent PR limits. Lockfile, minor/patch and Actions updates all require review: neither
Renovate nor platform auto-merge is enabled. Major-update dashboard approval is retained.

An Actions-pin update also requires a reviewed matching change to the repository's exact action
allowlist. A bot PR failing that policy is not justification for wildcard permissions or bypassing
protected-main checks. Existing service capabilities must not be handed to dependency-branch code.
The paused configuration and conservative merge defaults are covered by offline tests.

## Error remediation

A private error record is not a public issue template. Before enabling or retargeting an external
remediation controller, establish its actual project mapping and paused/enabled state. Approve
public-safe reproduction details rather than forwarding raw events, request/user data, host paths,
breadcrumbs, credentials or private links. New proposed fixes use normal reviewed pull requests and
ordinary unprivileged CI; an agent's claim of success is not release approval.

Preserve any existing pause until that controller's routing and output boundary are verified. Do not
reactivate shared automation, accept pending App permission increases, or change unrelated projects
merely to complete this repository's migration. A missing controller inventory remains an explicit
operational gap, not proof that no controller exists.

## Releases

Dependency or remediation changes do not authorize a live service restart. Marketing follows its
protected artifact-consumer gates; native game CI uses only disposable synthetic data. The dormant
game, production recovery, exact-digest acceptance and old/new writer fencing remain separate.
