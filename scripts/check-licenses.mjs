#!/usr/bin/env node
/**
 * Fails when a package listed in THIRD-PARTY-NOTICES.md is under a licence
 * that scripts/license-policy.json does not allow us to ship.
 *
 * It reads the package index tables of both generated regions (frontend npm
 * and backend Python), so it needs neither node_modules nor any venv. The
 * notices follow the lockfiles because CI already fails a pull request whose
 * notices are stale, which makes the committed file a faithful list of what
 * ships. The daily licence scan regenerates the file from scratch before
 * calling this, so a hand-edited row cannot hide a package for long.
 *
 * Usage:  node scripts/check-licenses.mjs [path/to/THIRD-PARTY-NOTICES.md]
 * Exit codes: 0 = every package acceptable, 1 = a problem (listed on stdout).
 */

import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

import { licenseProblem, toSpdxExpression } from './license-policy.mjs';

const REGIONS = ['frontend', 'backend'];

// Package rows look like "| `name` | version | licence | ...". The licence
// column may carry an escaped pipe ("\|"), so only an unescaped one splits.
export function packageRows(document) {
  const rows = Object.fromEntries(REGIONS.map((region) => [region, []]));
  let region = null;
  for (const line of document.replace(/\r\n/g, '\n').split('\n')) {
    const marker = /^<!-- (BEGIN|END) GENERATED: (\w+) -->$/.exec(line);
    if (marker) {
      region = marker[1] === 'BEGIN' && REGIONS.includes(marker[2]) ? marker[2] : null;
      continue;
    }
    if (region === null || !line.startsWith('| `')) continue;
    const cells = line.split(/(?<!\\)\|/).slice(1, -1).map((cell) => cell.trim().replace(/\\\|/g, '|'));
    rows[region].push({ name: cells[0].replace(/^`|`$/g, ''), version: cells[1], license: cells[2] });
  }
  return rows;
}

export function findProblems(document) {
  const problems = [];
  for (const [region, rows] of Object.entries(packageRows(document))) {
    // An empty region means the table format changed under us, not that nothing ships.
    if (rows.length === 0) {
      problems.push(`${region}: no packages found in THIRD-PARTY-NOTICES.md -- did the table format change?`);
      continue;
    }
    for (const { name, version, license } of rows) {
      const problem = licenseProblem(toSpdxExpression(license));
      if (problem) problems.push(`${region}: ${name}@${version}: licence "${license}" ${problem}`);
    }
  }
  return problems;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const noticesPath = process.argv[2] ?? fileURLToPath(new URL('../THIRD-PARTY-NOTICES.md', import.meta.url));
  const problems = findProblems(fs.readFileSync(noticesPath, 'utf8'));
  if (problems.length === 0) {
    console.log('Every shipped third-party package has an acceptable licence.');
    process.exit(0);
  }
  console.log(`${problems.length} shipped package(s) need their licence reviewed:\n`);
  console.log(problems.join('\n'));
  console.log(
    '\nCheck each licence. If its terms are acceptable, add its SPDX identifier to ' +
      'scripts/license-policy.json; otherwise remove or replace the package. A Python package ' +
      'whose metadata names no clear SPDX licence is pinned in SPDX_OVERRIDES in ' +
      'scripts/generate-python-notices.py after reading the licence text it ships.'
  );
  process.exit(1);
}
