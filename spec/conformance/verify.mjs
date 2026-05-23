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
import { readFileSync, existsSync } from "fs";
import { join, resolve } from "path";

// ── CSE codec ────────────────────────────────────────────────────

function parse(buf, off = 0) {
  if (buf[off] === 0x28) {          // '('
    const items = [];
    off++;
    while (buf[off] !== 0x29) {     // ')'
      const [v, next] = parse(buf, off);
      items.push(v);
      off = next;
    }
    return [items, off + 1];
  }
  const colon = buf.indexOf(0x3a, off);  // ':'
  const len = parseInt(buf.subarray(off, colon).toString(), 10);
  const start = colon + 1;
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

function computeNode(rule, version, sitedir) {
  const name    = rule[1];
  const recipe  = rule[2];
  const inputs  = rule[3];
  const outputs = rule[4];
  const children = rule.slice(5);

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
  const [tree] = parse(huskBuf);
  const version = tree[1];          // husk → version
  const build   = tree[2];          // husk → build
  const target  = build[3];         // build → target rule
  return computeNode(target, version, sitedir);
}

// ── CLI ──────────────────────────────────────────────────────────

const [huskPath, siteDir, expectedRoot] = process.argv.slice(2);
if (!huskPath || !siteDir) {
  console.error("usage: node verify.mjs <husk> <site> [expected-root]");
  process.exit(1);
}

const husk = readFileSync(resolve(huskPath));
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
