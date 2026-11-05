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
[guarded updater](game-deployment-controller.md), recovery checks and safe rollback require separate
installation, activation and operational acceptance.

The companion `rngwars-game-ssh.service` remains the unprivileged SSH entry point. A reviewed
installation can use `game_ssh_dispatch.py` to retain this probe and relay only the fixed deployment
verb to the separately isolated root worker; the SSH account itself never becomes privileged. Render
`configuration_file` privately. It provides OpenSSH's required runtime directory as well as its
project PID directory and preserves them on stop; no existing SSH configuration or keys are
replaced. `NoNewPrivileges=yes` intentionally prevents privilege escalation from the probe. Validate
the unit/configuration before installation, then verify actual key, forced-command, forwarding, PTY
and subsystem behavior without modifying production data.

## Protected read-only workflow

`.github/workflows/game-deployment.yml` keeps read-only verification separate from the explicitly
enabled, owner-reviewed `deploy` operation described in
[the updater guide](game-deployment-controller.md). Manual dispatch still defaults to
`verify-release`; it validates exact current main CI and fetches/verifies the selected published
image without private capability. `private-preflight` never invokes the mutating host command.

The optional `private-preflight` job additionally requires:

- `GAME_PRIVATE_PREFLIGHT_ENABLED=true` injected from repository configuration, not dispatch inputs.
- The pre-existing main-only, owner-reviewed `game-production` environment with no admin bypass.
- An actual owner approval for this first-attempt dispatch and a GitHub-hosted job.
- Two environment-scoped secrets: `GAME_NETWORK_BINDING` and `GAME_SSH_PRIVATE_KEY`. Never use a
  personal administrator key, historical package credential or long-lived Tailscale secret.

The private binding is a bounded JSON object with these exact fields:

| Field               | Binding                                                                  |
| ------------------- | ------------------------------------------------------------------------ |
| `client_id`         | Dedicated OIDC Client ID; no auth key or OAuth secret                    |
| `audience`          | Exact generated `api.tailscale.com/<client_id>` audience                 |
| `target_ipv4`       | Independently approved Tailscale address of the selected host            |
| `target_port`       | Approved separate OpenSSH listener port; not Tailscale SSH port 22       |
| `ssh_user`          | Dedicated `rngwars-deploy` account                                       |
| `host_public_key`   | Independently pinned `ssh-ed25519` host key, without a comment           |
| `denied_probe_ipv4` | Separately verified reachable Tailscale endpoint that CI must not access |

These are private operational bindings even where individual identifiers are nonsecret. The second
secret contains the dedicated restricted OpenSSH private key. Install both through secure stdin,
never command arguments, source, public artifacts or chat.

`scripts/game_network.py` rechecks GitHub context, fresh CI, environment/review and runner metadata
before staging credentials. It runs a checksum-pinned native Tailscale client in userspace mode with
memory-only ephemeral state, automatic GitHub OIDC discovery, one exact CI tag, incoming connections
blocked, and DNS/routes unchanged. SSH uses a private socket proxy, a pinned host key, the dedicated
key only, no agent and no forwarding. The server must return the exact fresh challenge.

After the positive SSH check, three negative connection checks must not connect: the target's
ordinary SSH and HTTPS ports and the independent denied endpoint's SSH port. A timeout alone does
not identify the cause of denial; pair runtime observations with independently validated policy and
endpoint reachability. Source tests use external tool doubles and do not establish live isolation.

Only bounded non-sensitive receipts are uploaded. Private daemon diagnostics are not public
artifacts. Normal completion logs out and stops only the owned daemon, then removes staged keys. The
workflow's `always()` cleanup also validates run ownership, process start identity and socket
arguments and uses a pidfd before terminating an interrupted run's daemon. It refuses foreign state
rather than deleting or killing by a broad name match. Failed or ambiguous attempts are inspected,
not blindly rerun. Hosted workflow acceptance remains separate from local tests and installed
listener acceptance; none of these preflight operations starts the game.
