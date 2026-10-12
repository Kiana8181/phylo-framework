/**
 * Proof of work for the sign-in forms' CAPTCHA (see apps/api/security/captcha.py).
 *
 * The server hands out a `challenge` and a `difficulty`. The answer is a number
 * `counter` such that SHA-256(`${challenge}:${counter}`) begins with at least
 * `difficulty` zero bits. Finding one takes about 2^difficulty hash
 * computations; checking one takes a single computation.
 *
 * SHA-256 is implemented here rather than taken from `crypto.subtle`: the
 * search needs a few hundred thousand hashes, and an awaited call per hash
 * would take many seconds. The part of the message that does not change (the
 * challenge) is hashed once; each attempt only hashes what follows it.
 */

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

const INITIAL = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];

/** Fold one 64-byte block (at `offset` in `data`) into `state`. `w` is scratch space. */
function compress(state: Uint32Array, data: Uint8Array, offset: number, w: Uint32Array): void {
  for (let i = 0; i < 16; i++) {
    const j = offset + i * 4;
    w[i] = ((data[j] << 24) | (data[j + 1] << 16) | (data[j + 2] << 8) | data[j + 3]) >>> 0;
  }
  for (let i = 16; i < 64; i++) {
    const a = w[i - 15];
    const b = w[i - 2];
    const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
    const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
    w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
  }
  let a = state[0], b = state[1], c = state[2], d = state[3];
  let e = state[4], f = state[5], g = state[6], h = state[7];
  for (let i = 0; i < 64; i++) {
    const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
    const ch = (e & f) ^ (~e & g);
    const t1 = (h + S1 + ch + K[i] + w[i]) >>> 0;
    const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
    const maj = (a & b) ^ (a & c) ^ (b & c);
    const t2 = (S0 + maj) >>> 0;
    h = g; g = f; f = e; e = (d + t1) >>> 0;
    d = c; c = b; b = a; a = (t1 + t2) >>> 0;
  }
  state[0] = (state[0] + a) >>> 0; state[1] = (state[1] + b) >>> 0;
  state[2] = (state[2] + c) >>> 0; state[3] = (state[3] + d) >>> 0;
  state[4] = (state[4] + e) >>> 0; state[5] = (state[5] + f) >>> 0;
  state[6] = (state[6] + g) >>> 0; state[7] = (state[7] + h) >>> 0;
}

/**
 * Finish a hash: `tail` holds the last `tailLength` bytes of a message whose
 * earlier bytes (a whole number of blocks) are already folded into `state`.
 * `tail` must have room for the padding (up to two blocks).
 */
function finish(state: Uint32Array, tail: Uint8Array, tailLength: number, totalLength: number, w: Uint32Array): void {
  let end = tailLength;
  tail[end++] = 0x80;
  const blocks = end > 56 ? 2 : 1;
  const size = blocks * 64;
  tail.fill(0, end, size - 8);
  const bits = totalLength * 8;
  // Message lengths here are far below 2^32 bytes: the high word of the bit length suffices.
  const high = Math.floor(bits / 0x100000000);
  const low = bits >>> 0;
  tail[size - 8] = high >>> 24; tail[size - 7] = (high >>> 16) & 0xff;
  tail[size - 6] = (high >>> 8) & 0xff; tail[size - 5] = high & 0xff;
  tail[size - 4] = low >>> 24; tail[size - 3] = (low >>> 16) & 0xff;
  tail[size - 2] = (low >>> 8) & 0xff; tail[size - 1] = low & 0xff;
  for (let block = 0; block < blocks; block++) compress(state, tail, block * 64, w);
}

/** SHA-256 of `bytes` as eight 32-bit words. */
export function sha256Words(bytes: Uint8Array): Uint32Array {
  const state = Uint32Array.from(INITIAL);
  const w = new Uint32Array(64);
  const whole = bytes.length - (bytes.length % 64);
  for (let offset = 0; offset < whole; offset += 64) compress(state, bytes, offset, w);
  const tail = new Uint8Array(128);
  tail.set(bytes.subarray(whole));
  finish(state, tail, bytes.length - whole, bytes.length, w);
  return state;
}

/** SHA-256 of a string (UTF-8), as lowercase hex. */
export function sha256Hex(text: string): string {
  const words = sha256Words(new TextEncoder().encode(text));
  let hex = "";
  for (let i = 0; i < 8; i++) hex += words[i].toString(16).padStart(8, "0");
  return hex;
}

/** Number of zero bits at the start of a digest given as 32-bit words. */
export function leadingZeroBits(words: Uint32Array): number {
  let bits = 0;
  for (let i = 0; i < words.length; i++) {
    if (words[i] === 0) {
      bits += 32;
      continue;
    }
    return bits + Math.clz32(words[i]);
  }
  return bits;
}

export type SolveOptions = {
  /** Abort the search (e.g. the form was closed). */
  signal?: AbortSignal;
  /** Hashes between two pauses that let the page stay responsive. */
  batch?: number;
};

/**
 * Find a counter that answers `challenge` at `difficulty`. Works in batches and
 * yields to the event loop between them, so the page keeps responding.
 */
export async function solveChallenge(challenge: string, difficulty: number, options: SolveOptions = {}): Promise<number> {
  const batch = Math.max(1, options.batch ?? 20_000);
  const prefix = new TextEncoder().encode(`${challenge}:`);
  const w = new Uint32Array(64);

  // Hash the unchanging whole blocks of the prefix once.
  const whole = prefix.length - (prefix.length % 64);
  const base = Uint32Array.from(INITIAL);
  for (let offset = 0; offset < whole; offset += 64) compress(base, prefix, offset, w);
  const rest = prefix.subarray(whole);

  const state = new Uint32Array(8);
  const tail = new Uint8Array(128);
  for (let counter = 0; ; counter++) {
    if (counter % batch === 0 && counter > 0) {
      if (options.signal?.aborted) throw new DOMException("The security check was cancelled.", "AbortError");
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    state.set(base);
    tail.set(rest);
    const digits = String(counter);
    for (let i = 0; i < digits.length; i++) tail[rest.length + i] = digits.charCodeAt(i);
    finish(state, tail, rest.length + digits.length, prefix.length + digits.length, w);
    if (leadingZeroBits(state) >= difficulty) return counter;
  }
}
