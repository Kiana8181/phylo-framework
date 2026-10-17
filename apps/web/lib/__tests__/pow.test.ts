import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { leadingZeroBits, sha256Hex, sha256Words, solveChallenge } from "../pow";

const reference = (text: string) => createHash("sha256").update(text, "utf8").digest();

function referenceZeroBits(text: string): number {
  let bits = 0;
  for (const byte of reference(text)) {
    if (byte === 0) { bits += 8; continue; }
    return bits + Math.clz32(byte) - 24;
  }
  return bits;
}

describe("SHA-256", () => {
  it("matches the published test vectors", () => {
    expect(sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(sha256Hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")).toBe(
      "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
    );
  });

  it("agrees with the platform implementation at every length around the block boundaries", () => {
    for (const length of [0, 1, 54, 55, 56, 57, 63, 64, 65, 119, 120, 121, 127, 128, 129, 200, 1000]) {
      const text = "x".repeat(length);
      expect(sha256Hex(text), `length ${length}`).toBe(reference(text).toString("hex"));
    }
    expect(sha256Hex("Ünïcödé ✓ 日本語")).toBe(reference("Ünïcödé ✓ 日本語").toString("hex"));
  });
});

describe("leading zero bits", () => {
  it.each([[[0xffffffff], 0], [[0x7fffffff], 1], [[0x00000001], 31], [[0, 0x80000000], 32], [[0, 0x00010000], 47], [[0, 0], 64]])(
    "%j has %d", (words, bits) => {
      expect(leadingZeroBits(Uint32Array.from(words as number[]))).toBe(bits);
    });
});

describe("solving a challenge", () => {
  // Shaped like the server's: a base64url payload, a dot, a 64-character signature.
  const challenge = "eyJkIjoxMiwiZSI6MTc5MDAwMDAwMCwibiI6Ikp4bzBJRjRkb1lPRnJYZ0xTdGFnUmcifQ." + "ab12".repeat(16);

  it("finds the smallest counter whose hash has enough leading zero bits", async () => {
    const difficulty = 12;
    const counter = await solveChallenge(challenge, difficulty);
    // The definition the server checks: SHA-256("<challenge>:<counter>").
    expect(referenceZeroBits(`${challenge}:${counter}`)).toBeGreaterThanOrEqual(difficulty);
    for (let earlier = 0; earlier < counter; earlier++) {
      expect(referenceZeroBits(`${challenge}:${earlier}`)).toBeLessThan(difficulty);
    }
  });

  it.each([1, 63, 64, 65, 127, 128, 200])("is right whatever the challenge length (%d)", async (length) => {
    const text = "c".repeat(length);
    const counter = await solveChallenge(text, 9);
    expect(referenceZeroBits(`${text}:${counter}`)).toBeGreaterThanOrEqual(9);
    expect(leadingZeroBits(sha256Words(new TextEncoder().encode(`${text}:${counter}`)))).toBeGreaterThanOrEqual(9);
  });

  it("pauses between batches and can be cancelled", async () => {
    const controller = new AbortController();
    const search = solveChallenge(challenge, 40, { signal: controller.signal, batch: 500 });   // far too hard to finish
    setTimeout(() => controller.abort(), 20);
    await expect(search).rejects.toMatchObject({ name: "AbortError" });
  });

  it("is fast enough for a form submission at the default difficulty", async () => {
    const started = performance.now();
    const counter = await solveChallenge(challenge, 18);
    expect(referenceZeroBits(`${challenge}:${counter}`)).toBeGreaterThanOrEqual(18);
    expect(performance.now() - started).toBeLessThan(15_000);
  }, 20_000);
});
