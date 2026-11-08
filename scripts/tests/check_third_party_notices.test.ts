import { describe, expect, test } from "bun:test";
import { findDrift, type Sources } from "../check_third_party_notices";

const lock = `{
  "lockfileVersion": 1,
  "workspaces": {
    "": { "name": "synthetic", "devDependencies": { "prettier": "3.9.9", }, },
    "apps/web": {
      "name": "@synthetic/web",
      "dependencies": { "@scope/widget": "^2.0.0", "left-pad": "1.0.0", },
      "devDependencies": { "wrangler": "4.158.0", },
    },
    "apps/site": {
      "name": "@synthetic/site",
      "dependencies": { "left-pad": "^1.0.0", },
    },
  },
  "packages": {
    "prettier": ["prettier@3.9.9", "", {}, "sha512-x"],
    "@scope/widget": ["@scope/widget@2.1.0", "", {}, "sha512-x"],
    "left-pad": ["left-pad@1.0.0", "", {}, "sha512-x"],
    "wrangler": ["wrangler@4.158.0", "", {}, "sha512-x"],
    "left-pad/transitive": ["transitive@9.9.9", "", {}, "sha512-x"],
  },
}`;

const javaScriptRows = [
  "| [@scope/widget](https://registry.npmjs.org/@scope%2fwidget/2.1.0) | 2.1.0 | MIT |",
  "| [left-pad](https://registry.npmjs.org/left-pad/1.0.0) | 1.0.0 | MIT |",
  "| [prettier](https://registry.npmjs.org/prettier/3.9.9) | 3.9.9 | MIT |",
  "| [wrangler](https://registry.npmjs.org/wrangler/4.158.0) | 4.158.0 | MIT OR Apache-2.0 |",
];

const nugetRows = ["| Giraffe | 8.3.0 | Apache-2.0 |", "| xunit | 2.* | Apache-2.0 |"];

const policyBullets = ["- `tree-sitter==0.25.2`: MIT.", "- `tree-sitter-yaml==0.7.2`: MIT."];

const notices = (overrides: { js?: string[]; nuget?: string[]; policy?: string[] } = {}) =>
  [
    "# Third-party notices",
    "## Direct JavaScript dependencies",
    "| Package | Version | Declared license |",
    "| --- | --- | --- |",
    ...(overrides.js ?? javaScriptRows),
    "Closing prose.",
    "## Backend and test dependencies",
    "| Package | Version / selector | License reference |",
    "| --- | --- | --- |",
    ...(overrides.nuget ?? nugetRows),
    "## Policy-checker dependencies",
    ...(overrides.policy ?? policyBullets),
    "## Original favicon",
  ].join("\n");

const sources = (overrides: Parameters<typeof notices>[0] & { lock?: string } = {}): Sources => ({
  lock: overrides.lock ?? lock,
  notices: notices(overrides),
  fsprojs: [
    `<ItemGroup><PackageReference Include="Giraffe" Version="8.3.0" /></ItemGroup>`,
    `<ItemGroup>\n<PackageReference Include="xunit" Version="2.*" />\n</ItemGroup>`,
  ],
  policyRequirements: "tree-sitter==0.25.2\ntree-sitter-yaml==0.7.2\n",
});

const replaceRow = (rows: string[], name: string, row: string | null) =>
  rows.flatMap((candidate) => (candidate.includes(`[${name}]`) ? (row ? [row] : []) : [candidate]));

describe("third-party notices versus lockfiles", () => {
  test("accepts a table that matches every lock", () => {
    expect(findDrift(sources())).toEqual([]);
  });

  test("names the row, the locked version and the link to use when a JavaScript version is stale", () => {
    const stale = replaceRow(
      javaScriptRows,
      "wrangler",
      "| [wrangler](https://registry.npmjs.org/wrangler/4.141.0) | 4.141.0 | MIT OR Apache-2.0 |"
    );
    expect(findDrift(sources({ js: stale }))).toEqual([
      `THIRD_PARTY_NOTICES.md "Direct JavaScript dependencies": row "wrangler" lists 4.141.0 but bun.lock pins 4.158.0. Set its Version cell to 4.158.0 and its link to https://registry.npmjs.org/wrangler/4.158.0.`,
    ]);
  });

  test("rejects a row whose link still points at an older version", () => {
    const stale = replaceRow(
      javaScriptRows,
      "prettier",
      "| [prettier](https://registry.npmjs.org/prettier/3.9.8) | 3.9.9 | MIT |"
    );
    expect(findDrift(sources({ js: stale }))).toEqual([
      `THIRD_PARTY_NOTICES.md "Direct JavaScript dependencies": row "prettier" links https://registry.npmjs.org/prettier/3.9.8 but should link https://registry.npmjs.org/prettier/3.9.9.`,
    ]);
  });

  test("reads the resolved version, not the declared range, and counts a shared dependency once", () => {
    const rows = javaScriptRows.filter((row) => row.includes("@scope") || row.includes("left-pad"));
    const errors = findDrift(sources({ js: rows }));
    expect(errors.some((error) => error.includes("2.1.0"))).toBe(false);
    expect(errors.filter((error) => error.includes("left-pad"))).toEqual([]);
  });

  test("asks for a row when a direct dependency is missing", () => {
    const errors = findDrift(sources({ js: replaceRow(javaScriptRows, "left-pad", null) }));
    expect(errors).toEqual([
      `THIRD_PARTY_NOTICES.md "Direct JavaScript dependencies": bun.lock has direct dependency "left-pad" 1.0.0 with no row. Add a row for it.`,
    ]);
  });

  test("asks for deletion when a row has no direct dependency", () => {
    const extra = [
      ...javaScriptRows,
      "| [tailwindcss](https://registry.npmjs.org/tailwindcss/4.0.0) | 4.0.0 | MIT |",
    ];
    expect(findDrift(sources({ js: extra }))).toEqual([
      `THIRD_PARTY_NOTICES.md "Direct JavaScript dependencies": row "tailwindcss" has no direct dependency in bun.lock. Delete that row.`,
    ]);
  });

  test("ignores transitive packages in the lock", () => {
    expect(findDrift(sources()).join()).not.toContain("transitive");
  });

  test("checks NuGet rows against the project files, selectors included", () => {
    const stale = ["| Giraffe | 8.2.0 | Apache-2.0 |", "| xunit | 2.9.* | Apache-2.0 |"];
    expect(findDrift(sources({ nuget: stale }))).toEqual([
      `THIRD_PARTY_NOTICES.md "Backend and test dependencies": row "Giraffe" lists 8.2.0 but apps/**/*.fsproj pins 8.3.0. Set its Version / selector cell to 8.3.0.`,
      `THIRD_PARTY_NOTICES.md "Backend and test dependencies": row "xunit" lists 2.9.* but apps/**/*.fsproj pins 2.*. Set its Version / selector cell to 2.*.`,
    ]);
  });

  test("checks policy-checker bullets against the requirements file", () => {
    const stale = ["- `tree-sitter==0.25.1`: MIT.", "- `tree-sitter-yaml==0.7.2`: MIT."];
    expect(findDrift(sources({ policy: stale }))).toEqual([
      `THIRD_PARTY_NOTICES.md "Policy-checker dependencies": row "tree-sitter" lists 0.25.1 but .comment-policy/requirements.txt pins 0.25.2. Change its bullet to \`tree-sitter==0.25.2\`.`,
    ]);
  });

  test("fails when a section is missing instead of passing vacuously", () => {
    const errors = findDrift({ ...sources(), notices: "# Third-party notices\n" });
    expect(errors).toHaveLength(3);
    expect(errors.every((error) => error.includes("no table rows found"))).toBe(true);
  });

  test("fails when two workspaces resolve a direct dependency to different versions", () => {
    const split = lock.replace(
      '"left-pad/transitive"',
      '"@synthetic/site/left-pad": ["left-pad@0.9.0", "", {}, "sha512-x"],\n    "left-pad/transitive"'
    );
    expect(findDrift(sources({ lock: split }))).toEqual([
      `bun.lock resolves "left-pad" to more than one version (1.0.0, 0.9.0). Make them agree; THIRD_PARTY_NOTICES.md can list only one.`,
    ]);
  });

  test("reports a repeated row instead of letting one copy hide the other", () => {
    const repeated = [
      "| [wrangler](https://registry.npmjs.org/wrangler/4.141.0) | 4.141.0 | MIT OR Apache-2.0 |",
      ...javaScriptRows,
    ];
    const errors = findDrift(sources({ js: repeated }));
    expect(errors).toContain(
      `THIRD_PARTY_NOTICES.md "Direct JavaScript dependencies": "wrangler" appears more than once (4.141.0, 4.158.0). Keep one row.`
    );
  });

  test("reports a row whose first cell is not a link", () => {
    const plain = replaceRow(javaScriptRows, "prettier", "| prettier | 3.9.9 | MIT |");
    expect(findDrift(sources({ js: plain }))).toEqual([
      `THIRD_PARTY_NOTICES.md "Direct JavaScript dependencies": row "prettier" links (no link) but should link https://registry.npmjs.org/prettier/3.9.9.`,
    ]);
  });

  test("skips workspace-protocol dependencies", () => {
    const internal = lock.replace(
      '"left-pad": "^1.0.0", },',
      '"left-pad": "^1.0.0", "@synthetic/web": "workspace:*", },'
    );
    expect(findDrift(sources({ lock: internal }))).toEqual([]);
  });

  test("rejects a NuGet license link that still names an older version", () => {
    const stale = [
      "| Giraffe | 8.3.0 | [Apache-2.0 metadata](https://api.nuget.org/v3-flatcontainer/giraffe/8.2.0/giraffe.nuspec) |",
      nugetRows[1]!,
    ];
    expect(findDrift(sources({ nuget: stale }))).toEqual([
      `THIRD_PARTY_NOTICES.md "Backend and test dependencies": row "Giraffe" has a license link naming 8.2.0 but the version is 8.3.0. Update the link.`,
    ]);
  });

  test("fails when two projects pin different versions of one NuGet package", () => {
    const drifted: Sources = {
      ...sources(),
      fsprojs: [
        `<PackageReference Version="8.0.0" Include="Giraffe" />`,
        `<PackageReference Include="Giraffe" Version="8.3.0" />`,
        `<PackageReference Include="xunit" Version="2.*" />`,
      ],
    };
    expect(findDrift(drifted)).toEqual([
      `apps/**/*.fsproj resolves "Giraffe" to more than one version (8.0.0, 8.3.0). Make them agree; THIRD_PARTY_NOTICES.md can list only one.`,
    ]);
  });

  test("reads a notices file with CRLF line endings", () => {
    const crlf = { ...sources(), notices: notices().replaceAll("\n", "\r\n") };
    expect(findDrift(crlf)).toEqual([]);
  });
});
