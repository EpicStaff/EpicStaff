#!/usr/bin/env node
/**
 * CI regression guard: fail when THIRD-PARTY-NOTICES.md no longer matches the
 * frontend lockfile it was generated from.
 *
 * Context: EST-3802. The notices file had drifted badly — it listed 402 packages
 * against a production tree of 63, including mermaid, katex, prismjs and xlsx,
 * none of which were dependencies any more. It is a licence attribution document,
 * so being wrong in either direction is a compliance problem, not cosmetics.
 *
 * The generator stamps the lockfile's sha256 into the file header, which makes
 * staleness detectable without re-running license-checker (and without network).
 *
 * Usage:  node scripts/check-third-party-notices.mjs
 * Exit codes: 0 = in sync, 1 = stale or unreadable.
 *
 * To fix a failure:  cd frontend && node scripts/generate-third-party-notices.mjs
 */

import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = join(fileURLToPath(import.meta.url), '..', '..');
const noticesPath = join(repoRoot, 'THIRD-PARTY-NOTICES.md');
const lockPath = join(repoRoot, 'frontend', 'package-lock.json');

const fail = (message) => {
  console.error(`Third-party notices check FAILED: ${message}`);
  process.exit(1);
};

for (const [label, p] of [
  ['THIRD-PARTY-NOTICES.md', noticesPath],
  ['frontend/package-lock.json', lockPath],
]) {
  if (!existsSync(p)) fail(`${label} does not exist.`);
}

const notices = readFileSync(noticesPath, 'utf8');
const stamped = notices.match(/<!-- package-lock\.json sha256: ([0-9a-f]+|no-lock) -->/)?.[1];

if (!stamped) {
  fail(
    'no lockfile hash in the header. The file must be produced by\n' +
      '  frontend/scripts/generate-third-party-notices.mjs, not edited by hand.'
  );
}

const actual = createHash('sha256').update(readFileSync(lockPath)).digest('hex').slice(0, 16);

if (stamped !== actual) {
  console.error(
    'Third-party notices check FAILED: THIRD-PARTY-NOTICES.md is stale.\n\n' +
      `  header records lockfile sha256  ${stamped}\n` +
      `  frontend/package-lock.json is   ${actual}\n\n` +
      'Production dependencies may have changed without the licence attribution\n' +
      'being updated. Regenerate and commit the result:\n\n' +
      '  cd frontend && node scripts/generate-third-party-notices.mjs\n'
  );
  process.exit(1);
}

const entries = (notices.match(/^### /gm) ?? []).length;
console.log(
  `Third-party notices check passed: ${entries} packages documented, header matches lockfile ${actual}.`
);
