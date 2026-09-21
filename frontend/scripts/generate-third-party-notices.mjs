#!/usr/bin/env node
/**
 * Regenerates the `frontend` region of THIRD-PARTY-NOTICES.md in the
 * repository root.
 *
 * Scope: production npm dependencies of the EpicStaff frontend
 * (declared in frontend/package.json dependencies, resolved via
 * frontend/package-lock.json), plus the embedded-assets notices
 * maintained by hand in frontend/scripts/embedded-assets-notices.md.
 * Backend / Python deps and frontend devDependencies are NOT included
 * - they are not shipped to users.
 *
 * This script only touches the text between the
 *   <!-- BEGIN GENERATED: frontend -->
 *   <!-- END GENERATED: frontend -->
 * markers in THIRD-PARTY-NOTICES.md. Everything else in that file
 * (static preamble, the backend region written by
 * scripts/generate-python-notices.py, and the static tail) is left
 * untouched.
 *
 * Usage (from frontend/ directory):
 *     node scripts/generate-third-party-notices.mjs
 *
 * Requires license-checker available at runtime. Invoked through
 * npx --yes license-checker so no devDependency entry is needed.
 */

import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..');
const OUTPUT_FILE = path.join(REPO_ROOT, 'THIRD-PARTY-NOTICES.md');
const SKELETON_FILE = path.join(REPO_ROOT, 'scripts', 'notices-skeleton.md');
const EMBEDDED_ASSETS_FILE = path.join(__dirname, 'embedded-assets-notices.md');

const REGION = 'frontend';
const BEGIN_MARKER = `<!-- BEGIN GENERATED: ${REGION} -->`;
const END_MARKER = `<!-- END GENERATED: ${REGION} -->`;

process.stderr.write('Running license-checker --production --json ...\n');
const isWin = process.platform === 'win32';
const lcCmd = isWin ? 'cmd.exe' : 'npx';
const lcArgs = isWin
  ? ['/c', 'npx', '--yes', 'license-checker', '--production', '--json']
  : ['--yes', 'license-checker', '--production', '--json'];
const lcResult = spawnSync(lcCmd, lcArgs, {
  cwd: FRONTEND_DIR,
  encoding: 'utf8',
  maxBuffer: 64 * 1024 * 1024,
});
if (lcResult.status !== 0) {
  process.stderr.write(lcResult.stderr || 'license-checker failed\n');
  process.exit(lcResult.status ?? 1);
}
const data = JSON.parse(lcResult.stdout);

const OWN_PKG_PREFIX = 'epicstaff-frontend@';

// Build entries
const entries = [];
for (const key of Object.keys(data).sort()) {
  if (key.startsWith(OWN_PKG_PREFIX)) continue; // skip own project
  const d = data[key];
  const atIdx = key.lastIndexOf('@');
  const name = key.substring(0, atIdx);
  const version = key.substring(atIdx + 1);

  let licenses = d.licenses || 'UNKNOWN';

  let licenseText = null;
  if (d.licenseFile) {
    try {
      const txt = fs.readFileSync(d.licenseFile, 'utf8');
      // Only include if it actually looks like a license (skip README files used as fallback)
      const lower = d.licenseFile.toLowerCase();
      if (lower.includes('license') || lower.includes('copying') || lower.includes('notice')) {
        licenseText = txt.trim();
      }
    } catch (e) { /* ignore */ }
  }

  entries.push({
    name, version, licenses,
    repository: d.repository || null,
    publisher: d.publisher || null,
    url: d.url || null,
    email: d.email || null,
    licenseText,
    licenseFile: d.licenseFile || null,
  });
}

// License distribution
const dist = {};
for (const e of entries) dist[e.licenses] = (dist[e.licenses] || 0) + 1;

const generatedAt = new Date().toUTCString().replace(/\s+/g, ' ');
const gitShaResult = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: REPO_ROOT, encoding: 'utf8' });
const gitSha = gitShaResult.status === 0 ? gitShaResult.stdout.trim() : 'UNKNOWN';
const lockFilePath = path.join(FRONTEND_DIR, 'package-lock.json');
const lockHash = fs.existsSync(lockFilePath)
  ? createHash('sha256').update(fs.readFileSync(lockFilePath)).digest('hex').slice(0, 16)
  : 'no-lock';

// Build markdown for the frontend region body
const lines = [];
lines.push('<!-- AUTO-GENERATED — do not edit by hand -->');
lines.push(`<!-- generated: ${generatedAt} -->`);
lines.push(`<!-- commit: ${gitSha} -->`);
lines.push(`<!-- package-lock.json sha256: ${lockHash} -->`);
lines.push('');
lines.push('## Frontend license summary');
lines.push('');
lines.push('Production npm dependencies of the Angular frontend. Assets embedded in the prebuilt widget bundle are counted separately under "Embedded assets" below, and backend Python packages under "Backend (Python)".');
lines.push('');
lines.push('| License | Packages |');
lines.push('|---|---|');
const distEntries = Object.entries(dist).sort((a, b) => b[1] - a[1]);
for (const [lic, cnt] of distEntries) {
  lines.push(`| ${lic} | ${cnt} |`);
}
lines.push(`| **Total** | **${entries.length}** |`);
lines.push('');
lines.push('## Package index');
lines.push('');
lines.push('| Package | Version | License |');
lines.push('|---|---|---|');
for (const e of entries) {
  const safeName = e.name.replace(/\|/g, '\|');
  lines.push(`| \`${safeName}\` | ${e.version} | ${e.licenses} |`);
}
lines.push('');
lines.push('---');
lines.push('');
lines.push('## Notices');
lines.push('');
lines.push('Per-package copyright notices and license texts. License text is included verbatim when the upstream package ships a LICENSE/COPYING/NOTICE file; otherwise the SPDX identifier and any available publisher / repository metadata are recorded.');
lines.push('');

for (const e of entries) {
  lines.push(`### ${e.name}@${e.version}`);
  lines.push('');
  lines.push(`- **License:** ${e.licenses}`);
  if (e.publisher) lines.push(`- **Publisher:** ${e.publisher}${e.email ? ' <' + e.email + '>' : ''}`);
  if (e.repository) lines.push(`- **Repository:** ${e.repository}`);
  else if (e.url) lines.push(`- **URL:** ${e.url}`);
  lines.push('');
  if (e.licenseText) {
    lines.push('<details><summary>License text</summary>');
    lines.push('');
    lines.push('```');
    lines.push(e.licenseText);
    lines.push('```');
    lines.push('');
    lines.push('</details>');
    lines.push('');
  } else {
    lines.push('_No LICENSE file shipped with this package; license identifier shown above._');
    lines.push('');
  }
}

lines.push('---');
lines.push('');
lines.push('## Vendored code');
lines.push('');
lines.push('Third-party code copied into this repository rather than installed as a dependency. `license-checker` cannot see it, so these entries are maintained by hand in the generator.');
lines.push('');
lines.push('### ngx-json-viewer');
lines.push('');
lines.push('`frontend/src/app/shared/components/json-viewer/` is derived from [ngx-json-viewer](https://github.com/hivivo/ngx-json-viewer) 3.2.1. The library was unmaintained since November 2022, declared no peer dependency ranges and was built for Angular 14, so it gave no compatibility signal on framework upgrades; it was vendored and rewritten for standalone components and block control flow. The segment model, type detection and CSS class contract come from the original and are reproduced below under its licence.');
lines.push('');
lines.push('```');
lines.push('MIT License');
lines.push('');
lines.push('Copyright (c) 2022 Vivo Xu');
lines.push('');
lines.push('Permission is hereby granted, free of charge, to any person obtaining a copy');
lines.push('of this software and associated documentation files (the "Software"), to deal');
lines.push('in the Software without restriction, including without limitation the rights');
lines.push('to use, copy, modify, merge, publish, distribute, sublicense, and/or sell');
lines.push('copies of the Software, and to permit persons to whom the Software is');
lines.push('furnished to do so, subject to the following conditions:');
lines.push('');
lines.push('The above copyright notice and this permission notice shall be included in all');
lines.push('copies or substantial portions of the Software.');
lines.push('');
lines.push('THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR');
lines.push('IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,');
lines.push('FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE');
lines.push('AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER');
lines.push('LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,');
lines.push('OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE');
lines.push('SOFTWARE.');
lines.push('```');
lines.push('');
lines.push('### JSON-js cycle.js');
lines.push('');
lines.push('The cycle-removal helper in the same component follows [Douglas Crockford\'s cycle.js](https://github.com/douglascrockford/JSON-js/blob/master/cycle.js), which its author released into the public domain. No licence notice is required for it; it is recorded here for completeness.');
lines.push('');

let body = lines.join('\n');

// Inline the hand-maintained embedded-assets notices, if present.
if (fs.existsSync(EMBEDDED_ASSETS_FILE)) {
  const embedded = fs.readFileSync(EMBEDDED_ASSETS_FILE, 'utf8').trim();
  body = body + '\n' + embedded;
} else {
  process.stderr.write(`Warning: ${EMBEDDED_ASSETS_FILE} not found; skipping embedded assets section.\n`);
}

// Splice the region body into THIRD-PARTY-NOTICES.md, touching nothing
// outside the BEGIN/END GENERATED: frontend markers.
let existingText;
if (fs.existsSync(OUTPUT_FILE)) {
  existingText = fs.readFileSync(OUTPUT_FILE, 'utf8');
} else if (fs.existsSync(SKELETON_FILE)) {
  existingText = fs.readFileSync(SKELETON_FILE, 'utf8');
} else {
  process.stderr.write(
    `Error: neither ${OUTPUT_FILE} nor ${SKELETON_FILE} exists. Cannot determine document structure.\n`
  );
  process.exit(1);
}
existingText = existingText.replace(/\r\n/g, '\n');

const docLines = existingText.split('\n');
let beginIdx = -1;
let endIdx = -1;
let beginCount = 0;
let endCount = 0;
for (let i = 0; i < docLines.length; i++) {
  if (docLines[i] === BEGIN_MARKER) { beginCount++; beginIdx = i; }
  if (docLines[i] === END_MARKER) { endCount++; endIdx = i; }
}
if (beginCount !== 1 || endCount !== 1 || beginIdx === -1 || endIdx === -1 || endIdx < beginIdx) {
  process.stderr.write(
    `Error: could not find exactly one well-formed marker pair\n` +
    `  ${BEGIN_MARKER}\n  ${END_MARKER}\n` +
    `in ${OUTPUT_FILE}. Restore the marker pair from ${SKELETON_FILE} and try again.\n`
  );
  process.exit(1);
}

const before = docLines.slice(0, beginIdx + 1).join('\n');
const after = docLines.slice(endIdx).join('\n');
let finalMd = before + '\n' + body.trim() + '\n' + after;
finalMd = finalMd.replace(/\s+$/, '') + '\n';

fs.writeFileSync(OUTPUT_FILE, finalMd, 'utf8');
process.stderr.write('Discovered ' + entries.length + ' third-party packages.\nUpdated frontend region of ' + OUTPUT_FILE + '\n');
