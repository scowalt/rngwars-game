# Third-party notices

The root MIT license applies to owner-controlled original RNGWars source and documentation. It does
not relicense dependency code, data, trademarks or license texts. Dependencies are obtained
separately through Bun/NuGet/uv; this source snapshot does not include `node_modules`, NuGet
binaries, Python packages, compiled assets, container images or the application's historical
third-party assets.

[THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt) preserves available license/notice texts from
the installed direct dependency distributions, plus the upstream xUnit abstractions notice. These
supplementary texts are not a complete redistribution manifest for every possible build output.

## Direct JavaScript dependencies

Versions below are the locked versions, including development tooling. Package publisher metadata is
linked for verification; the package's actual license/notice files take precedence over a summary.

| Package                                                                       | Version  | Declared license                      |
| ----------------------------------------------------------------------------- | -------- | ------------------------------------- |
| [@microsoft/signalr](https://registry.npmjs.org/@microsoft%2fsignalr/10.0.11) | 10.0.11  | MIT                                   |
| [@sentry/browser](https://registry.npmjs.org/@sentry%2fbrowser/10.75.3)       | 10.75.3  | MIT                                   |
| [@solidjs/router](https://registry.npmjs.org/@solidjs%2frouter/0.16.3)        | 0.16.3   | MIT                                   |
| [solid-js](https://registry.npmjs.org/solid-js/1.9.15)                        | 1.9.15   | MIT                                   |
| [posthog-js](https://registry.npmjs.org/posthog-js/1.434.15)                  | 1.434.15 | Apache-2.0 AND MIT                    |
| [@tailwindcss/vite](https://registry.npmjs.org/@tailwindcss%2fvite/4.3.3)     | 4.3.3    | MIT                                   |
| [tailwindcss](https://registry.npmjs.org/tailwindcss/4.3.3)                   | 4.3.3    | MIT                                   |
| [typescript](https://registry.npmjs.org/typescript/6.0.3)                     | 6.0.3    | Apache-2.0                            |
| [vite](https://registry.npmjs.org/vite/8.3.1)                                 | 8.3.1    | MIT, with bundled third-party notices |
| [vite-plugin-solid](https://registry.npmjs.org/vite-plugin-solid/2.11.14)     | 2.11.14  | MIT                                   |
| [vitest](https://registry.npmjs.org/vitest/4.1.11)                            | 4.1.11   | MIT, with bundled third-party notices |
| [jsdom](https://registry.npmjs.org/jsdom/30.1.1)                              | 30.1.1   | MIT                                   |
| [@astrojs/solid-js](https://registry.npmjs.org/@astrojs%2fsolid-js/7.0.2)     | 7.0.2    | MIT                                   |
| [astro](https://registry.npmjs.org/astro/7.3.5)                               | 7.3.5    | MIT, with bundled third-party notices |
| [@astrojs/check](https://registry.npmjs.org/@astrojs%2fcheck/0.9.10)          | 0.9.10   | MIT                                   |
| [wrangler](https://registry.npmjs.org/wrangler/4.141.0)                       | 4.141.0  | MIT OR Apache-2.0                     |
| [lefthook](https://registry.npmjs.org/lefthook/2.1.14)                        | 2.1.14   | MIT                                   |
| [markdownlint-cli](https://registry.npmjs.org/markdownlint-cli/0.49.1)        | 0.49.1   | MIT                                   |
| [prettier](https://registry.npmjs.org/prettier/3.9.9)                         | 3.9.9    | MIT                                   |

PostHog's `AND` expression requires attention to both licenses; it is not permission to select just
one. Wrangler and Lefthook remain in the unchanged dependency graph, but this snapshot has no
hosting deployment command and installs no Git hooks.

## Backend and test dependencies

| Package                       | Version / selector | License reference                                                                                                                              |
| ----------------------------- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| dbup-sqlite                   | 6.0.4              | [MIT package metadata](https://api.nuget.org/v3-flatcontainer/dbup-sqlite/6.0.4/dbup-sqlite.nuspec)                                            |
| Sentry.AspNetCore             | 6.11.1             | [MIT package metadata](https://api.nuget.org/v3-flatcontainer/sentry.aspnetcore/6.11.1/sentry.aspnetcore.nuspec)                               |
| SQLitePCLRaw.bundle_e_sqlite3 | 3.0.5              | [Apache-2.0 package metadata](https://api.nuget.org/v3-flatcontainer/sqlitepclraw.bundle_e_sqlite3/3.0.5/sqlitepclraw.bundle_e_sqlite3.nuspec) |
| Donald                        | 10.1.0             | [Apache-2.0 package metadata](https://api.nuget.org/v3-flatcontainer/donald/10.1.0/donald.nuspec)                                              |
| Giraffe                       | 8.3.0              | Apache-2.0; included package `LICENSE` text is reproduced in the accompanying notice file                                                      |
| Microsoft.Data.Sqlite         | 10.0.11            | [MIT package metadata](https://api.nuget.org/v3-flatcontainer/microsoft.data.sqlite/10.0.11/microsoft.data.sqlite.nuspec)                      |
| Microsoft.NET.Test.Sdk        | 18.1*              | [MIT upstream](https://github.com/microsoft/vstest/blob/main/LICENSE)                                                                          |
| xunit                         | 2.*                | [Apache-2.0 upstream](https://github.com/xunit/xunit/blob/main/LICENSE)                                                                        |
| xunit.runner.visualstudio     | 3.*                | [Apache-2.0 upstream](https://github.com/xunit/visualstudio.xunit/blob/main/License.txt)                                                       |

Test-tool versions currently float in the project file. Inspect the resolved restore graph rather
than treating a selector as a fixed version. The older transitive `xunit.abstractions@2.0.3` package
uses a legacy license URL rather than an SPDX expression; see its
[upstream Apache-2.0 notice](https://github.com/xunit/abstractions.xunit/blob/main/license.txt). The
native SQLite package identifies SQLite as [public domain](https://sqlite.org/copyright.html); its
.NET wrappers have their own licenses.

## Policy-checker dependencies

The parser environment in `.comment-policy/requirements.txt` contains:

- `tree-sitter==0.25.2`: MIT.
- `tree-sitter-language-pack==0.13.0`: MIT OR Apache-2.0, with bundled grammar notices to retain
  when redistributing the package.
- `tree-sitter-c-sharp==0.23.5`: MIT.
- `tree-sitter-embedded-template==0.25.0`: MIT.
- `tree-sitter-yaml==0.7.2`: MIT.

Operational tests additionally use PyYAML as pinned in `ops/tests/requirements.txt`, under its MIT
license. OpenTofu, Restic, TFLint, Checkov, Docker tooling and GitHub Actions retain their own
upstream licenses; they are invoked or downloaded separately, not relicensed by this repository.

These tools are not vendored into this source snapshot.

## Transitive dependencies and future distributions

The installed Linux dependency graph is not entirely MIT/Apache licensed. Notable examples are:

- Lightning CSS and its native packages: MPL-2.0. Mozilla describes its
  [file-level copyleft and distribution requirements](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).
- Sharp's prebuilt libvips packages: LGPL-3.0-or-later, as declared by the
  [package publisher](https://registry.npmjs.org/@img%2fsharp-libvips-linux-x64/1.3.3). These are
  build-tool dependencies, not RNGWars-owned code. Redistributing native binaries is a separate
  licensing task; consult the [LGPL](https://www.gnu.org/licenses/lgpl-3.0.html).
- `caniuse-lite`: CC-BY-4.0 data, with its own attribution conditions.
- DOMPurify: MPL-2.0 OR Apache-2.0; preserve the terms of the selected licensing path.
- Other packages include BSD, ISC, MIT-0, Blue Oak, Python and public-domain-style terms.

Dependency versions, platform-specific packages and build outputs can change the applicable
obligations. If distributing browser bundles, native executables, dependency directories or images,
review their complete contents, preserve copyright/license/NOTICE material and satisfy any
applicable source-availability or relinking requirements. Source-only publication is not blanket
approval for binary or image distribution. Do not strip legal comments as ordinary source-policy
cleanup.

## Original favicon

`apps/marketing_site/public/favicon.svg` is an original drawing composed of a rounded square and
five circles, included under the root MIT license. It uses no downloaded fonts, framework logo or
third-party artwork. No rights to third-party trademarks are granted.
