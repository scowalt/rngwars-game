# Marketing artifact preparation

`scripts/marketing_artifact.py` supplies bounded asset packaging and CI/source validation.
`marketing-artifact.yml` produces signed, public release candidates using trusted-main controller
code. It does not deploy anything or carry production credentials. An internally consistent manifest
alone is not authorization or proof of authentic provenance.

## Implemented interfaces

- `pack(directory, destination)` creates a deterministic ZIP from regular static files, including
  `index.html` and `_headers`. It rejects links, special files, hidden/unsafe paths and oversized
  input. Existing output files are never overwritten. Packing requires a POSIX filesystem.
- `assets(bytes)` validates a ZIP and returns its files in memory. No archive paths are extracted to
  disk and no asset content is executed. Names must be unique, bounded relative ASCII paths.
- `bundle(bytes, identity, destination)` creates a normalized asset bundle with an explicit source,
  workflow and run identity and a SHA-256/size inventory. This is **not a signature**.
- `inspect_bundle(bytes)` verifies the manifest and file inventory. Caller-written identities are
  not authenticated merely because the manifest is internally consistent.
- `resolve_ci(run_id, workflow_revision)` reads GitHub REST metadata for this repository. It
  requires a completed successful first-attempt push/manual CI run, the exact expected successful
  job set, matching repository IDs, current source/default-branch revisions and an unchanged CI
  workflow definition. Fork/PR merge runs, skipped jobs, changed CI definitions and superseded
  revisions are rejected. This establishes a CI/source binding, not artifact provenance or a full
  third-party branch-protection rollup.

Limits are 2,000 assets, 25 MiB per asset, 50 MiB total asset bytes and 64 MiB compressed archives.
The bundle permits one additional manifest of at most 1 MiB. ZIP links, duplicate entries,
unsupported compression, encrypted entries, malformed JSON and duplicate JSON keys are rejected.

## Signed candidate workflow

```text
exact successful push/manual CI
  → protected-main resolver
  → source build with read-only contents access
  → fresh trusted-main job validates bytes and reconstructs the manifest
  → GitHub OIDC/SLSA attestation
  → cryptographic verification
  → immutable candidate artifact
```

CI runs on all branch pushes to establish exact-head results for preview candidates. Pull-request
merge validation remains separate. Fork/PR-merge runs cannot enter the signing graph. The producer
runs from main through `workflow_run`, or manual dispatch with an explicit successful CI run ID.
Only first attempts and current source/controller revisions are accepted. Superseded builds fail
closed; per-branch concurrency does not promise an archive of every intermediate revision.

Source execution and signing use separate GitHub-hosted runners. The source job gets no OIDC,
attestation, package, deployment, private-network or production-secret capability. The signing job
checks out only trusted-main code, installs no source dependencies, validates the exact upstream
artifact ID/run/repository/transport digest, and never extracts or executes source-built files. Only
that job has `id-token: write` and `attestations: write`; ordinary CI stays read-only.

The attestation covers the complete bundle, including the independently reconstructed manifest. The
manifest identifies the actual tested source; the attestation's workflow identity identifies the
trusted controller, which may be a different revision for previews. Verification uses GitHub CLI
with an exact main workflow certificate identity, signer/source digest, ref and invocation, and
rejects self-hosted signers. It fetches authentic attestations from GitHub, not caller-provided
JSON. The CLI and GitHub-hosted platform are part of the verifier's trust base; missing verifier
support fails closed. Only read-only verification receives bounded consistency retries.

All artifacts, source/run identifiers and attestations are public. The build includes legal notices
and leaves product analytics unset, matching the reviewed native build configuration. Artifact
creation does not itself approve production use. Production settings and behavior must be checked
again as part of the controlled cutover.

The exact action allowlist must include the pinned `actions/attest-build-provenance` action and its
pinned `actions/attest` dependency. Neither blanket GitHub-owned action permission nor weakened SHA
pinning is required.

## Remaining release requirements

The [protected release consumer](marketing-release.md) separately verifies completed producer
status, exact artifact ID/digest and trusted signer revision; it never trusts names or manifests
alone. It adds environment protection, encrypted diagnostics, immutable attempt reservations,
controller fencing and rollback. Its enablement and live acceptance are separate from candidate
creation. No Cloudflare controller, game publisher, private package grant or live service is changed
by the candidate workflow.

See [the release boundary](release-boundary.md). Tests use synthetic assets and API responses;
passing them is not a live release or recovery acceptance test.

```bash
python3 -m unittest discover -s scripts/tests -p 'test_marketing*.py' -v
```
