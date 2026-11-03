# Native ARM64 game image validation

`Native game image` builds the actual production Docker target on a GitHub-hosted ARM64 runner. It
does not publish an image, use a private runner, connect to a game host, or access real data. Image
architecture and configured non-root user/entrypoint are verified before runtime checks.

The runtime harness is restricted to this repository's hosted ARM64 context. It creates one uniquely
named and labeled disposable Docker volume. Testing mode initializes only that synthetic fixture.
Production mode must reject the empty population, then accept the same fixture after an anonymous
test identity has been created. The token and changed username must survive a restart into
Production mode. Practice-match creation, bundled frontend delivery and included legal notices are
checked. Production must also reject a missing database without creating it.

The deployment template and fixture both enable Docker's init process (`init: true` / `--init`). A
native comparison found that a fatal startup exception left .NET running as PID 1; changing only the
init setting made the same image/database exit with code134. This preserves the database refusal
rather than accepting a hung process as a successful negative test. Direct image operators must also
use `--init`. No database guard was weakened and no live deployment was changed.

Every application container uses `--network none`, no published ports and a read-only root
filesystem. HTTP requests run inside that container's own loopback namespace via `docker exec`; this
is not a browser-accessible development server or a public/Tailscale endpoint. No local
server/container is started by the agent. Service credentials, analytics and error reporting are
absent from the fixture. Synthetic bearer values are kept out of command arguments and evidence;
failure logs redact synthetic UUIDs.

Only a bounded JSON receipt is uploaded. It records the actual checkout revision (a PR merge
revision for PR runs), native/image architecture, local image identity and completed checks. It is
not a registry manifest digest or signed image-publication receipt. The fixture database is never
uploaded. Owned containers/volume are removed, including on failure; no shared cleanup command is
used.

The image includes the project's license and third-party notices. Their inclusion is not a blanket
legal determination for every dependency or base image. Native smoke success is not production-host,
backup, restore, state-ownership or data-recovery acceptance. The intentionally dormant game is not
restarted by this workflow. Publishing and live recovery retain their separate safeguards.
