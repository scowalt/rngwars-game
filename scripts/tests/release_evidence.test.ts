import { describe, expect, test } from "bun:test";
import { decrypt, encrypt, type Context } from "../release_evidence";

const context: Context = {
  repository_id: 1442331254,
  run_id: "42",
  artifact_sha256: "a".repeat(64),
  kind: "preview",
};
const key = Buffer.alloc(32, 7).toString("base64");

describe("private release evidence", () => {
  test("retains detail without plaintext and authenticates the exact public context", async () => {
    const detail = { version: "synthetic-private-version", endpoint: "synthetic-private-resource" };
    const encrypted = await encrypt(context, detail, key);
    expect(encrypted).not.toContain(detail.version);
    expect(encrypted).not.toContain(detail.endpoint);
    expect(await decrypt(encrypted, context, key)).toEqual(detail);
    await expect(decrypt(encrypted, { ...context, run_id: "43" }, key)).rejects.toThrow();
    await expect(
      decrypt(encrypted, context, Buffer.alloc(32, 8).toString("base64"))
    ).rejects.toThrow();
  });
  test("uses fresh nonces and rejects modified ciphertext", async () => {
    const first = await encrypt(context, { status: "synthetic" }, key);
    const second = await encrypt(context, { status: "synthetic" }, key);
    expect(first).not.toEqual(second);
    const modified = JSON.parse(first);
    const bytes = Buffer.from(modified.ciphertext, "base64");
    bytes[0] = bytes[0]! ^ 1;
    modified.ciphertext = bytes.toString("base64");
    await expect(decrypt(JSON.stringify(modified), context, key)).rejects.toThrow();
  });
  test("rejects wrong repositories, unbounded details and invalid keys", async () => {
    await expect(encrypt({ ...context, repository_id: 1 }, {}, key)).rejects.toThrow();
    await expect(encrypt(context, "x".repeat(300000), key)).rejects.toThrow();
    await expect(encrypt(context, {}, "not-a-key")).rejects.toThrow();
  });
});
