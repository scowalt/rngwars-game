# Private game deployment preparation

These interfaces prepare private deployment; they do not start the game, install a service, or
complete the deployment controller. Public activation remains separately gated.

## Credential-free release verification

Fetch and verify an exact published release into a new private directory:

```sh
python3 scripts/game_release.py fetch /absolute/new-directory \
  --revision FULL_SOURCE_SHA \
  --digest sha256:FULL_IMAGE_DIGEST \
  --publication-run SUCCESSFUL_PUBLICATION_RUN_ID
```

The command retrieves the manifest/config from the public release namespace, genuine attestations
from GitHub, and Sigstore trusted roots through the GitHub CLI's verified TUF flow. It verifies:

- Exact manifest/config digests, bounded OCI descriptors and the Linux ARM64 runtime identity.
- A successful first-attempt owner-dispatched main publication, including all four expected jobs and
  the native runner. A signature from an otherwise failed publication is insufficient.
- Genuine provenance with the exact trusted workflow, issuer, source/signer SHA, main ref, hosted
  runner, image subject and publication invocation.

No GitHub or registry account credential is passed to child tools. Anonymous registry pull tokens
stay in memory/private stdin, never command arguments or output. Config blobs may use one HTTPS
redirect to the fixed GitHub container CDN; registry authorization is not forwarded there. Arbitrary
origins, redirects, external descriptors and existing output destinations are rejected. No image
layers are downloaded or executed.

The output directory contains only `manifest.json`, `config.json`, `bundle.jsonl` and
`trusted-root.jsonl`. Files are published only after verification. Inputs are snapshotted privately
before invoking the verifier, preventing subsequent input changes from changing the checked bytes.
Errors do not print raw tool/provider diagnostics.

Previously obtained evidence can be checked with:

```sh
python3 scripts/game_release.py verify \
  /absolute/manifest.json /absolute/config.json /absolute/bundle.jsonl \
  --trusted-root /absolute/trusted-root.jsonl \
  --revision FULL_SOURCE_SHA \
  --digest sha256:FULL_IMAGE_DIGEST \
  --publication-run SUCCESSFUL_PUBLICATION_RUN_ID
```

The operator must establish the trusted-root file through a trusted installation/TUF flow. A future
host command must not accept an arbitrary trust root from a remote request. Both commands report
`release_verified_not_deployment_approval`: release verification does not establish deployment
review, host/storage identity, backup readiness or permission to alter a workload. `curl` and a
GitHub CLI with offline attestation support are required. Anonymous provider rate limits fail
closed.

## Restricted SSH transport preparation

Tailscale SSH intercepts port 22 on a device's Tailscale address and does not apply OpenSSH's
`authorized_keys` command restrictions. Keep existing administrator access intact. A separately
approved project-only OpenSSH listener can bind an explicit private address/port, with its own host
key, account and restricted authorized key. Do not alter a shared SSH daemon or expose a public
port.

`ops/production/game-deployment/sshd_config.template` is a template, not an installable
configuration. Render and validate its exact private bindings before installation. It permits one
named non-root user using public-key authentication and a fixed command; forwarding, PTY,
environment acceptance, user startup files, root login and subsystems are disabled. Preserve
existing services and keys. Runtime connection tests remain necessary: `sshd -T` proves effective
configuration, not access.

For initial transport verification, the fixed command can run the unprivileged standalone
`scripts/game_ssh_probe.py` under isolated Python (`python3 -I`). It accepts only
`SSH_ORIGINAL_COMMAND=rngwars-game-preflight-v1` and a bounded JSON request on stdin:

```json
{ "version": 1, "challenge": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
```

The actual client must generate a fresh random 64-character lowercase hexadecimal challenge. The
probe echoes only that challenge and `restricted_transport_only`. It rejects other commands,
interactive terminals, extra arguments/fields, duplicate keys and unfinished/oversized input. It
runs no subprocesses and accesses no database, backup credentials or Docker socket. The deployment
account must not receive those privileges merely to test transport.

An echo from this probe is not application health, a release approval or a completed deployment. The
protected OIDC workflow, actual network isolation, privileged fixed host controller, recovery checks
and safe rollback still need independent implementation and operational acceptance.
