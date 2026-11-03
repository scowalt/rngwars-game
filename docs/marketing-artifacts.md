# Marketing artifact preparation

`scripts/marketing_artifact.py` is a library for the credential-free part of marketing CD. It is not
an enabled producer workflow or deployment command. No release permission follows from packaging
files or inspecting a manifest.

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

## Remaining release requirements

A trusted-main producer still needs to build without deployment credentials, independently construct
and sign the bundle in a separate job, and verify its authentic attestation. A consumer must bind
the exact artifact ID/digest and trusted signer, not select by name or accept arbitrary manifest
claims. Protected release capabilities, private diagnostics, a durable conditional-create attempt
ledger, production/preview controller fencing and rollback are separate prerequisites. No publisher,
credential, environment, trigger or live service is changed by this library.

See [the release boundary](release-boundary.md). Tests use synthetic assets and API responses;
passing them is not a live release or recovery acceptance test.

```bash
python3 -m unittest discover -s scripts/tests -p test_marketing_artifact.py -v
```
