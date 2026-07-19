#!/usr/bin/env node
/**
 * Client bundle-size budget — the JS every route pays for.
 *
 * Bundle weight only ever grows, one "small" dependency at a time, and nobody notices until the
 * app is slow on a real phone. This measures the **shared client bundle** (`rootMainFiles` +
 * polyfills from Next's build manifest) — the bytes every route downloads — and fails when it
 * exceeds the budget.
 *
 * Why this is gate-able where a general performance budget is not: a Lighthouse-style score is
 * environment-sensitive and flaky in CI, but these are the same bytes on every run of the same
 * commit. Measured **gzipped**, because that is what users actually download.
 *
 * The default budget is derived from a real measurement of the freshly generated app
 * (~167 kB gzipped shared) with roughly 50% headroom — NOT an invented round number. A budget
 * that goes red the day you add your first real dependency teaches people to raise it
 * reflexively, which is worse than having none.
 *
 *   node scripts/check-bundle-size.mjs [--max-kb 250]
 *   BUNDLE_MAX_KB=200 npm run bundle-size
 */
import { readFileSync, existsSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const argIndex = process.argv.indexOf("--max-kb");
const MAX_KB = Number(
  argIndex !== -1
    ? process.argv[argIndex + 1]
    : (process.env.BUNDLE_MAX_KB ?? 250),
);

if (!Number.isFinite(MAX_KB) || MAX_KB <= 0) {
  console.error(
    `bundle-size: invalid budget '${MAX_KB}' — pass --max-kb <n> or set BUNDLE_MAX_KB.`,
  );
  process.exit(1);
}

const manifestPath = join(process.cwd(), ".next", "build-manifest.json");
if (!existsSync(manifestPath)) {
  console.error(
    "bundle-size: .next/build-manifest.json not found — run `npm run build` first.",
  );
  process.exit(1);
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const files = [
  ...(manifest.rootMainFiles ?? []),
  ...(manifest.polyfillFiles ?? []),
];

if (files.length === 0) {
  // Fail rather than pass vacuously: a manifest shape we don't understand must not look green.
  console.error(
    "bundle-size: no rootMainFiles/polyfillFiles in the build manifest — the Next build output " +
      "shape changed. Fix this script rather than letting the budget silently stop measuring.",
  );
  process.exit(1);
}

let bytes = 0;
for (const file of files) {
  const path = join(process.cwd(), ".next", file);
  if (existsSync(path))
    bytes += gzipSync(readFileSync(path), { level: 6 }).length;
}

const kb = bytes / 1024;
const rounded = kb.toFixed(1);

if (kb > MAX_KB) {
  console.error(
    `bundle-size: FAILED — shared client bundle is ${rounded} kB gzipped, over the ${MAX_KB} kB budget.\n` +
      "  Trim or lazy-load a dependency, or raise BUNDLE_MAX_KB deliberately (and say why in the PR).",
  );
  process.exit(1);
}

console.log(
  `bundle-size: OK — shared client bundle ${rounded} kB gzipped (budget ${MAX_KB} kB, ${files.length} files).`,
);
