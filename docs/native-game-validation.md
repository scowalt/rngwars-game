# Native ARM64 game image validation

`Native game image` builds the actual production Docker target on a GitHub-hosted ARM64 runner. It
does not publish an image, use a private runner, connect to a game host, or access real data. Image
architecture and configured non-root user/entrypoint are verified before runtime checks.

The runtime harness is restricted to this repository's hosted ARM64 context. It creates one uniquely
named and labeled disposable Docker volume. Testing mode creates an unmarked empty negative fixture,
which Production must reject. The real image then runs the explicit offline initializer as the data
owner, while root invocation must fail. Invalid listening/database environment settings demonstrate
that the initializer uses only its explicit path and exits without starting the web host.

That newly initialized empty file is copied into a private runner directory and backed up/restored
through the real operator and an isolated encrypted local Restic repository. No real storage service
or credentials are involved. Full snapshot equivalence and repository checks must pass. The restored
file is placed at another new path in the owned volume; Production must accept it with an empty
leaderboard before the first signup. The token and changed username must survive a Production
restart. Practice-match creation, bundled frontend and legal notices are checked. A pinned Bun
client shares only the fixture's network namespace and joins two real SignalR clients sequentially.
Both must observe countdown, rolling, reveal and completion, with persisted ratings and history.
This covers the second player's transition from Connecting without host ports or runtime egress.
Production also must reject a missing database without creating it. Original synthetic files are not
overwritten.

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
uploaded. Owned containers/volume and local encrypted fixture storage are removed, including on
failure; no shared cleanup command is used.

The image includes the project's license and third-party notices. Their inclusion is not a blanket
legal determination for every dependency or base image. Native smoke success proves only synthetic
local backup/restore, not production-host, real off-host backup/recovery or state-ownership
acceptance. The intentionally dormant game is not restarted by this workflow. Publishing and live
recovery retain their separate safeguards.
