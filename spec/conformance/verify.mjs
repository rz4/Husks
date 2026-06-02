#!/usr/bin/env node
// verify.mjs — Independent CSE reader and husk verifier (Node.js)
//
// Zero dependencies beyond Node.js stdlib (crypto, fs, path).
// Implements the CSE-v1 spec from scratch to prove permanence:
// a husk sealed by the original engine verifies under a reader
// in a language the engine never knew.
//
// Usage: node verify.mjs <husk-file> <site-dir> [expected-root]

import { createHash } from "crypto";
import { readFileSync, existsSync, statSync } from "fs";
import { join, resolve } from "path";

// ── Bounded read guard ──────────────────────────────────────────
const MAX_HUSK_BYTES = 10 * 1024 * 1024; // 10 MB

// ── CSE codec ────────────────────────────────────────────────────

const MAX_PARSE_DEPTH = 128;                    // Match core.py's _MAX_PARSE_DEPTH
const MAX_ATOM_LENGTH = 256 * 1024 * 1024;      // 256 MB, match core.py's _MAX_ATOM_LENGTH

function parse(buf, off = 0, depth = 0) {
  if (depth > MAX_PARSE_DEPTH) {
    throw new Error(`nesting depth exceeds ${MAX_PARSE_DEPTH} at offset ${off}`);
  }
  if (off >= buf.length) throw new Error("unexpected EOF");
  if (buf[off] === 0x28) {          // '('
    const items = [];
    off++;
    while (off < buf.length && buf[off] !== 0x29) {
      const [v, next] = parse(buf, off, depth + 1);
      items.push(v);
      off = next;
    }
    if (off >= buf.length) throw new Error("unterminated list");
    return [items, off + 1];
  }
  const colon = buf.indexOf(0x3a, off);  // ':'
  if (colon < 0) throw new Error("missing colon in atom");

  const lengthBytes = buf.subarray(off, colon);

  // Validate each byte is an ASCII digit (0x30-0x39)
  for (let i = 0; i < lengthBytes.length; i++) {
    const b = lengthBytes[i];
    if (b < 0x30 || b > 0x39) {  // '0' .. '9'
      throw new Error(`non-digit byte 0x${b.toString(16).padStart(2, '0')} in length at offset ${off + i}`);
    }
  }

  const lenStr = lengthBytes.toString();
  if (lenStr.length > 1 && lenStr[0] === "0") {
    throw new Error("leading zero in atom length");
  }

  const len = parseInt(lenStr, 10);  // Safe now that we've validated digit-only

  if (len > MAX_ATOM_LENGTH) {
    throw new Error(`atom length ${len} exceeds maximum ${MAX_ATOM_LENGTH} at offset ${off}`);
  }

  const start = colon + 1;
  if (start + len > buf.length) throw new Error("atom overruns input");
  return [buf.subarray(start, start + len), start + len];
}

function encode(val) {
  if (Buffer.isBuffer(val))
    return Buffer.concat([Buffer.from(`${val.length}:`), val]);
  const parts = val.map(encode);
  return Buffer.concat([Buffer.from("("), ...parts, Buffer.from(")")]);
}

// ── Hashing ──────────────────────────────────────────────────────

const sha256 = (data) => createHash("sha256").update(data).digest("hex");
const ABSENT = Buffer.from("absent");

function fileHash(sitedir, name) {
  const p = join(sitedir, name.toString());
  return existsSync(p) ? Buffer.from(sha256(readFileSync(p))) : ABSENT;
}

// ── Seal & Merkle ────────────────────────────────────────────────

function recipeDigest(recipe) { return sha256(encode(recipe)); }

function computeSeal(version, recipe, inputs, sitedir) {
  const rd = Buffer.from(recipeDigest(recipe));
  const bindings = inputs.map((n) => [n, fileHash(sitedir, n)]);
  const preimage = [Buffer.from("seal"), version, rd, bindings];
  return sha256(encode(preimage));
}

function computeNode(node, version, sitedir) {
  const tag = node[0].toString();

  // Terminal nodes: digest is the hash of their CSE encoding
  if (tag === "commit" || tag === "halt")
    return sha256(encode(node));

  // Cond nodes
  if (tag === "cond") {
    const thenDigest = computeNode(node[2], version, sitedir);
    const elseDigest = computeNode(node[3], version, sitedir);
    const condForm = [
      Buffer.from("cond"), node[1],
      Buffer.from(thenDigest), Buffer.from(elseDigest),
    ];
    return sha256(encode(condForm));
  }

  // Rule node
  const name    = node[1];
  const recipe  = node[2];
  const inputs  = node[3];
  const outputs = node[4];
  const children = node.slice(5);

  const childDigests = children.map((c) =>
    Buffer.from(computeNode(c, version, sitedir))
  );

  const seal = computeSeal(version, recipe, inputs, sitedir);
  const outBindings = outputs.map((o) => [o, fileHash(sitedir, o)]);
  const nodeForm = [
    Buffer.from("node"), name, Buffer.from(seal), outBindings, childDigests,
  ];
  return sha256(encode(nodeForm));
}

function recomputeRoot(huskBuf, sitedir) {
  const [tree, next] = parse(huskBuf);
  if (next !== huskBuf.length)
    throw new Error(`trailing data at offset ${next} (${huskBuf.length - next} bytes)`);
  const version = tree[1];          // husk → version
  const build   = tree[2];          // husk → build
  const targets = build.slice(3);   // all target nodes
  if (targets.length === 1)
    return computeNode(targets[0], version, sitedir);
  const perRoots = targets
    .map((t) => computeNode(t, version, sitedir))
    .sort();
  return sha256(Buffer.from(perRoots.join("")));
}

// ── CLI ──────────────────────────────────────────────────────────

const [huskPath, siteDir, expectedRoot] = process.argv.slice(2);
if (!huskPath || !siteDir) {
  console.error("usage: node verify.mjs <husk> <site> [expected-root]");
  process.exit(1);
}

try {
  const huskResolved = resolve(huskPath);
  const huskSize = statSync(huskResolved).size;
  if (huskSize > MAX_HUSK_BYTES) {
    console.error(`error: husk file too large (${huskSize} bytes, max ${MAX_HUSK_BYTES})`);
    process.exit(1);
  }
  const husk = readFileSync(huskResolved);
  const root = recomputeRoot(husk, resolve(siteDir));

  console.log(root);

  if (expectedRoot) {
    if (root === expectedRoot.trim()) {
      console.log("PASS — root matches");
      process.exit(0);
    } else {
      console.error(`FAIL — expected ${expectedRoot.trim()}, got ${root}`);
      process.exit(1);
    }
  }
} catch (e) {
  console.error(`error: ${e.message}`);
  process.exit(1);
}
