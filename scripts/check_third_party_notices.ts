import { Glob } from "bun";
import { join } from "node:path";

export interface Sources {
  lock: string;
  notices: string;
  fsprojs: string[];
  policyRequirements: string;
}

interface Lock {
  workspaces: Record<
    string,
    {
      name: string;
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
      optionalDependencies?: Record<string, string>;
    }
  >;
  packages: Record<string, [string, ...unknown[]]>;
}

type Entry = [name: string, value: string];

const NOTICES = "THIRD_PARTY_NOTICES.md";

const registryUrl = (name: string, version: string) =>
  `https://registry.npmjs.org/${name.replace("/", "%2f")}/${version}`;

function section(markdown: string, heading: string): string[] {
  const lines = markdown.split(/\r?\n/);
  const start = lines.findIndex((line) => line === `## ${heading}`);
  if (start < 0) return [];
  const end = lines.findIndex((line, index) => index > start && line.startsWith("## "));
  return lines.slice(start + 1, end < 0 ? undefined : end);
}

function tableRows(markdown: string, heading: string): string[][] {
  return section(markdown, heading)
    .filter((line) => line.startsWith("|"))
    .slice(2)
    .map((line) =>
      line
        .slice(1, line.lastIndexOf("|"))
        .split("|")
        .map((cell) => cell.trim())
    );
}

interface Collapsed {
  map: Map<string, string>;
  conflicts: Set<string>;
  errors: string[];
}

function collapse(
  entries: Entry[],
  conflict: (name: string, values: string[]) => string | undefined
): Collapsed {
  const groups = new Map<string, string[]>();
  for (const [name, value] of entries) groups.set(name, [...(groups.get(name) ?? []), value]);
  const messages = new Map([...groups].map(([name, values]) => [name, conflict(name, values)]));
  return {
    map: new Map([...groups].map(([name, values]) => [name, values[0] ?? ""])),
    conflicts: new Set([...messages].flatMap(([name, message]) => (message ? [name] : []))),
    errors: [...messages.values()].flatMap((message) => message ?? []),
  };
}

function compare(
  heading: string,
  lockName: string,
  listed: Collapsed,
  locked: Collapsed,
  rowHint: (name: string, version: string) => string
): string[] {
  const where = `${NOTICES} "${heading}"`;
  const skipped = (name: string) => listed.conflicts.has(name) || locked.conflicts.has(name);
  const errors = [...listed.errors, ...locked.errors];
  if (listed.map.size === 0) {
    return [...errors, `${where}: no table rows found; the check cannot pass vacuously.`];
  }
  for (const [name, version] of listed.map) {
    const actual = locked.map.get(name);
    if (skipped(name)) continue;
    if (actual === undefined) {
      errors.push(
        `${where}: row "${name}" has no direct dependency in ${lockName}. Delete that row.`
      );
    } else if (actual !== version) {
      errors.push(
        `${where}: row "${name}" lists ${version} but ${lockName} pins ${actual}. ${rowHint(name, actual)}`
      );
    }
  }
  for (const [name, version] of locked.map) {
    if (!listed.map.has(name) && !skipped(name)) {
      errors.push(
        `${where}: ${lockName} has direct dependency "${name}" ${version} with no row. Add a row for it.`
      );
    }
  }
  return errors;
}

function lockedJavaScript(lock: Lock): Entry[] {
  return Object.values(lock.workspaces).flatMap((workspace) =>
    Object.entries({
      ...workspace.dependencies,
      ...workspace.devDependencies,
      ...workspace.optionalDependencies,
    })
      .filter(([, spec]) => !spec.startsWith("workspace:"))
      .map(([name]): Entry => {
        const ident = (lock.packages[`${workspace.name}/${name}`] ?? lock.packages[name])?.[0];
        if (!ident) throw new Error(`bun.lock has no resolved package for "${name}"`);
        return [name, ident.slice(ident.lastIndexOf("@") + 1)];
      })
  );
}

const duplicateRow = (heading: string) => (name: string, values: string[]) =>
  values.length > 1
    ? `${NOTICES} "${heading}": "${name}" appears more than once (${values.join(", ")}). Keep one row.`
    : undefined;

const splitVersions = (lockName: string) => (name: string, values: string[]) =>
  new Set(values).size > 1
    ? `${lockName} resolves "${name}" to more than one version (${[...new Set(values)].join(", ")}). Make them agree; ${NOTICES} can list only one.`
    : undefined;

function javaScriptErrors(notices: string, lockText: string): string[] {
  const heading = "Direct JavaScript dependencies";
  const rows = tableRows(notices, heading).map(([link = "", version = ""]) => {
    const match = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(link);
    return { name: match?.[1] ?? link, url: match?.[2] ?? "", version };
  });
  const listed = collapse(
    rows.map((row): Entry => [row.name, row.version]),
    duplicateRow(heading)
  );
  const locked = collapse(
    lockedJavaScript(Bun.JSONC.parse(lockText) as Lock),
    splitVersions("bun.lock")
  );
  const errors = [
    ...compare(
      heading,
      "bun.lock",
      listed,
      locked,
      (name, version) =>
        `Set its Version cell to ${version} and its link to ${registryUrl(name, version)}.`
    ),
  ];
  for (const row of rows) {
    if (
      locked.map.get(row.name) === row.version &&
      row.url !== registryUrl(row.name, row.version)
    ) {
      errors.push(
        `${NOTICES} "${heading}": row "${row.name}" links ${row.url || "(no link)"} but should link ${registryUrl(row.name, row.version)}.`
      );
    }
  }
  return errors;
}

function nugetErrors(notices: string, fsprojs: string[]): string[] {
  const heading = "Backend and test dependencies";
  const rows = tableRows(notices, heading).map(([name = "", version = "", license = ""]) => ({
    name,
    version,
    license,
  }));
  const listed = collapse(
    rows.map((row): Entry => [row.name, row.version]),
    duplicateRow(heading)
  );
  const references = fsprojs.flatMap((project) =>
    [...project.matchAll(/<PackageReference\b[^>]*>/g)].flatMap(([tag = ""]): Entry[] => {
      const include = /\bInclude="([^"]+)"/.exec(tag)?.[1];
      const version = /\bVersion="([^"]+)"/.exec(tag)?.[1];
      return include && version ? [[include, version]] : [];
    })
  );
  const locked = collapse(references, splitVersions("apps/**/*.fsproj"));
  const errors = [
    ...compare(
      heading,
      "apps/**/*.fsproj",
      listed,
      locked,
      (_, version) => `Set its Version / selector cell to ${version}.`
    ),
  ];
  for (const row of rows) {
    const named = [...row.license.matchAll(/\/(\d+\.\d+\.\d+)\//g)].map((match) => match[1]);
    if (
      locked.map.get(row.name) === row.version &&
      named.some((version) => version !== row.version)
    ) {
      errors.push(
        `${NOTICES} "${heading}": row "${row.name}" has a license link naming ${named.join(", ")} but the version is ${row.version}. Update the link.`
      );
    }
  }
  return errors;
}

function policyErrors(notices: string, requirements: string): string[] {
  const heading = "Policy-checker dependencies";
  const bullets = section(notices, heading).flatMap((line): Entry[] => {
    const match = /^- `([^`=]+)==([^`]+)`/.exec(line);
    return match?.[1] && match[2] ? [[match[1], match[2]]] : [];
  });
  const pins = requirements.split(/\r?\n/).flatMap((line): Entry[] => {
    const match = /^([^=\s]+)==(\S+)$/.exec(line.trim());
    return match?.[1] && match[2] ? [[match[1], match[2]]] : [];
  });
  const listed = collapse(bullets, duplicateRow(heading));
  const locked = collapse(pins, splitVersions(".comment-policy/requirements.txt"));
  return [
    ...compare(
      heading,
      ".comment-policy/requirements.txt",
      listed,
      locked,
      (name, version) => `Change its bullet to \`${name}==${version}\`.`
    ),
  ];
}

export function findDrift(sources: Sources): string[] {
  return [
    ...javaScriptErrors(sources.notices, sources.lock),
    ...nugetErrors(sources.notices, sources.fsprojs),
    ...policyErrors(sources.notices, sources.policyRequirements),
  ];
}

async function readSources(root: string): Promise<Sources> {
  const text = (path: string) => Bun.file(join(root, path)).text();
  const paths = await Array.fromAsync(new Glob("apps/**/*.fsproj").scan({ cwd: root }));
  return {
    lock: await text("bun.lock"),
    notices: await text(NOTICES),
    fsprojs: await Promise.all(paths.sort().map(text)),
    policyRequirements: await text(".comment-policy/requirements.txt"),
  };
}

if (import.meta.main) {
  const errors = findDrift(await readSources(join(import.meta.dir, "..")));
  for (const error of errors) console.error(error);
  if (errors.length > 0) process.exit(1);
  console.log(
    `${NOTICES} matches bun.lock, the .fsproj files and .comment-policy/requirements.txt.`
  );
}
