# Protected marketing releases

The release controller consumes signed candidates; it never rebuilds or executes candidate code. An
exact successful producer run, artifact ID, transport digest, authenticated bundle signature,
current source revision and trusted-main workflow revision are rechecked before protected work.

## Controls

- `Marketing release` runs from main after the candidate workflow, or by explicit producer run ID.
  Manual dispatch defaults to `validate`. `preflight` checks protected bindings and writes encrypted
  evidence without provider mutations. `deploy` additionally requires
  `MARKETING_RELEASE_ENABLED=true`.
- Production and preview use separate main-only environments with owner review. The administrative
  bypass option is disabled. Self-review is allowed for the single-maintainer workflow; normal
  review is still required. Source builds cannot access either environment.
- Only the release job gets GitHub contents-write permission, for an immutable attempt tag
  containing public source/run/artifact identifiers. A tag ruleset rejects updates and deletion of
  attempt tags. The controller creates refs once; it never rewrites, deletes or retries a
  reservation.
- Private service bindings and credentials are environment secrets, not repository variables or
  checked-in configuration. Default CI and preparation remain read-only. Bun executable caching is
  disabled in credential-bearing jobs; no application dependencies are installed there.
- Both replaced native build triggers must exclude every branch, with their exact identities and a
  complete idle build inventory verified. This fence is checked again before production promotion.
  Trigger changes are an operator cutover step, not an automatic permission probe.

## Provider operations

The direct API adapter uploads validated static assets and creates an assets-only version. Header
and redirect rules are carried as asset configuration, not Worker code. Existing Worker identity,
compatibility settings, bindings and routing are checked/preserved; no Worker or DNS record is
created.

Preview uploads must leave the active production version unchanged. If version-preview serving was
already disabled, it stays disabled and acceptance uses version metadata. The controller does not
silently expose new preview URLs. When serving is enabled, its documented version URL is checked.
Production promotion is a separate exact-version request, followed by active-version and public
content/asset checks. Known health failure causes at most one rollback to the captured version. An
ambiguous write is resolved by readback where possible, never blindly repeated.

## Private evidence and recovery

Detailed operation evidence is encrypted with AES-GCM and an independent key before object storage.
Public run/artifact context is authenticated as associated data. Credentials and temporary upload
JWTs are removed before serialization. No raw provider output, resource identifiers, preview
hostnames or decrypted evidence is emitted to public Actions logs or artifacts.

Conditional object creation rejects overwrites and readback is authenticated. The uploader enforces
bounded records, pagination and a1GiB bucket budget. Existing storage retention does not remove the
permanent Git attempt reservation. Account administrators remain part of the accepted trust model;
these controls are not isolation from a compromised owner account.

`release_evidence.ts` accepts a private JSON input over stdin. Its `read` operation requires an
exact public context, storage credentials, encryption key and a new absolute `output_directory`. It
refuses GitHub Actions execution, creates a0700 directory and a0600 `evidence.json`, and prints only
a bounded receipt. Use it locally with the dedicated secret-manager configuration; never put values
in argv or commit the decrypted directory. Key rotation must retain keys needed for retained
evidence.

Before restoring native trigger filters, disable/drain the replacement controller. Preserve the
saved filters and active version. Do not clear attempt tags or initialize/reset application data to
make a failed release pass. Data-bearing game recovery has independent backup and artifact approval
gates.

## Current behavior

Marketing builds preserve the native controller's absent analytics build setting rather than enable
an unused secret-manager value. Enabling product analytics is a separate configuration change. The
candidate pipeline and ordinary CI stay available even while release execution is disabled.

Tests cover unsafe/mismatched artifacts, caller context, controller fences, separate
preview/promotion, output rejection, lost replies, rollback and authenticated private evidence. Live
provider and cutover verification remain necessary; synthetic tests alone are not operational
acceptance.
