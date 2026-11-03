import { mkdir, writeFile } from "node:fs/promises";
import { isAbsolute, join } from "node:path";

export interface Context {
  repository_id: number;
  run_id: string;
  artifact_sha256: string;
  kind: "production" | "preview";
}

const bytes = (value: string) => new TextEncoder().encode(value);
const encoded = (value: ArrayBuffer | Uint8Array) => Buffer.from(value).toString("base64");
const canonical = (context: Context) =>
  JSON.stringify({
    repository_id: context.repository_id,
    run_id: context.run_id,
    artifact_sha256: context.artifact_sha256,
    kind: context.kind,
  });
function check(value: unknown): asserts value {
  if (!value) throw new Error("release_evidence_rejected");
}
function validate(context: Context) {
  check(
    JSON.stringify(Object.keys(context).sort()) ===
      JSON.stringify(["artifact_sha256", "kind", "repository_id", "run_id"])
  );
  check(
    context.repository_id === 1442331254 &&
      /^[1-9][0-9]{0,19}$/.test(context.run_id) &&
      /^[a-f0-9]{64}$/.test(context.artifact_sha256) &&
      ["production", "preview"].includes(context.kind)
  );
}
export async function encrypt(context: Context, record: unknown, key: string) {
  validate(context);
  const raw = Buffer.from(key, "base64");
  check(raw.length === 32 && raw.toString("base64") === key);
  const content = bytes(JSON.stringify(record));
  check(content.length <= 256 * 1024);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const secret = await crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt"]);
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: nonce, additionalData: bytes(canonical(context)) },
    secret,
    content
  );
  return JSON.stringify({
    version: 1,
    key_version: 1,
    context,
    nonce: encoded(nonce),
    ciphertext: encoded(ciphertext),
  });
}
export async function decrypt(text: string, expected: Context, key: string) {
  validate(expected);
  check(text.length <= 512 * 1024);
  const envelope = JSON.parse(text);
  validate(envelope.context);
  check(Buffer.from(envelope.nonce, "base64").length === 12);
  check(
    envelope.version === 1 &&
      envelope.key_version === 1 &&
      canonical(envelope.context) === canonical(expected)
  );
  const raw = Buffer.from(key, "base64");
  check(raw.length === 32 && raw.toString("base64") === key);
  const secret = await crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["decrypt"]);
  const result = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: Buffer.from(envelope.nonce, "base64"),
      additionalData: bytes(canonical(expected)),
    },
    secret,
    Buffer.from(envelope.ciphertext, "base64")
  );
  return JSON.parse(new TextDecoder().decode(result));
}

if (import.meta.main) {
  try {
    const input = await Bun.stdin.json();
    check(/^https:\/\/[a-f0-9]{32}\.r2\.cloudflarestorage\.com$/.test(input.endpoint));
    check(/^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/.test(input.bucket));
    check(/^[a-z0-9-]{1,32}$/.test(input.phase));
    const context: Context = input.context;
    validate(context);
    check(input.operation === undefined || ["write", "read"].includes(input.operation));
    const key = `rngwars-release/${context.run_id}/${input.phase}.json`;
    const client = new Bun.S3Client({
      endpoint: input.endpoint,
      bucket: input.bucket,
      region: "auto",
      accessKeyId: input.access_key,
      secretAccessKey: input.secret_key,
      retry: 0,
    });
    if (input.operation === "read") {
      check(
        process.env.GITHUB_ACTIONS !== "true" &&
          typeof input.output_directory === "string" &&
          isAbsolute(input.output_directory)
      );
      check((await client.file(key).stat()).size <= 512 * 1024);
      const record = await decrypt(await client.file(key).text(), context, input.encryption_key);
      await mkdir(input.output_directory, { mode: 0o700 });
      await writeFile(
        join(input.output_directory, "evidence.json"),
        JSON.stringify(record, null, 2) + "\n",
        { flag: "wx", mode: 0o600 }
      );
      console.log(JSON.stringify({ status: "private_evidence_downloaded", phase: input.phase }));
      process.exit(0);
    }
    const text = await encrypt(context, input.record, input.encryption_key);
    let total = Buffer.byteLength(text);
    let continuation: string | undefined;
    const tokens = new Set<string>();
    for (let page = 0; ; page++) {
      check(page < 10);
      const listing = await client.list({ maxKeys: 1000, continuationToken: continuation });
      for (const item of listing.contents ?? []) {
        check(Number.isSafeInteger(item.size) && item.size! >= 0);
        total += item.size!;
      }
      check(total <= 1024 * 1024 * 1024);
      if (!listing.isTruncated) break;
      continuation = listing.nextContinuationToken;
      check(continuation && !tokens.has(continuation));
      tokens.add(continuation);
    }
    const url = client.presign(key, { method: "PUT", expiresIn: 60, type: "application/json" });
    const response = await fetch(url, {
      method: "PUT",
      redirect: "manual",
      headers: { "content-type": "application/json", "if-none-match": "*" },
      body: text,
      signal: AbortSignal.timeout(20000),
    });
    check(response.ok);
    check((await client.file(key).stat()).size <= 512 * 1024);
    const stored = await client.file(key).text();
    check(stored === text);
    await decrypt(stored, context, input.encryption_key);
    console.log(JSON.stringify({ status: "private_evidence_retained", phase: input.phase }));
  } catch {
    console.error("Private release evidence unavailable; raw diagnostics withheld");
    process.exitCode = 1;
  }
}
