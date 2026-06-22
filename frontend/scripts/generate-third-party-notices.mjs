#!/usr/bin/env node
/**
 * Generates THIRD-PARTY-NOTICES.md in the repository root.
 *
 * Scope: production npm dependencies of the EpicStaff frontend
 * (declared in frontend/package.json dependencies, resolved via
 * frontend/package-lock.json). Backend / Python deps and frontend
 * devDependencies are NOT included - they are not shipped to users.
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

const OWN_PKG_PREFIX = 'frontend-crewai@';

// Build entries
const entries = [];
for (const key of Object.keys(data).sort()) {
  if (key.startsWith(OWN_PKG_PREFIX)) continue; // skip own project
  const d = data[key];
  const atIdx = key.lastIndexOf('@');
  const name = key.substring(0, atIdx);
  const version = key.substring(atIdx + 1);

  // license override: @openai/realtime-api-beta is MIT per its own package.json
  let licenses = d.licenses || 'UNKNOWN';
  if (name === '@openai/realtime-api-beta') licenses = 'MIT';

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

// Build markdown
const lines = [];
lines.push('<!-- AUTO-GENERATED — do not edit by hand -->');
lines.push(`<!-- generated: ${generatedAt} -->`);
lines.push(`<!-- commit: ${gitSha} -->`);
lines.push(`<!-- package-lock.json sha256: ${lockHash} -->`);
lines.push('');
lines.push('# Third-Party Notices');
lines.push('');
lines.push('This file lists third-party open-source software bundled into the EpicStaff frontend (Angular application). It covers **production** npm dependencies declared in `frontend/package.json` and resolved via `frontend/package-lock.json`.');
lines.push('');
lines.push('Backend / Python dependencies are out of scope of this file. Development-only npm dependencies (test runners, linters, build tooling) are likewise out of scope, since they are not shipped with the production bundle.');
lines.push('');
lines.push('The EpicStaff project itself is licensed under the terms found in [LICENSE](./LICENSE). Nothing in this notices file modifies or supersedes that license.');
lines.push('');
lines.push('---');
lines.push('');
lines.push('## License summary');
lines.push('');
lines.push('| License | Packages |');
lines.push('|---|---|');
const distEntries = Object.entries(dist).sort((a, b) => b[1] - a[1]);
for (const [lic, cnt] of distEntries) {
  lines.push(`| ${lic} | ${cnt} |`);
}
lines.push(`| **Total** | **${entries.length}** |`);
lines.push('');
lines.push('---');
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
lines.push('## How to refresh this file');
lines.push('');
lines.push('Whenever frontend production dependencies change (additions, version bumps, removals in `frontend/package.json`), regenerate this notices file.');
lines.push('');
lines.push('From the repository root, in PowerShell:');
lines.push('');
lines.push('```powershell');
lines.push('cd frontend');
lines.push('npm install');
lines.push('node scripts/generate-third-party-notices.mjs');
lines.push('cd ..');
lines.push('```');
lines.push('');
lines.push('The generator script lives at `frontend/scripts/generate-third-party-notices.mjs` and invokes `npx --yes license-checker --production --json` internally - no extra devDependency is needed. The output is written to `THIRD-PARTY-NOTICES.md` at the repository root, overwriting the previous version.');
lines.push('');
lines.push('### What the refresh covers');
lines.push('');
lines.push('- Walks every package reachable from `frontend/package.json` `dependencies` (not `devDependencies`) via `npm` resolution.');
lines.push('- Reads each package\'s SPDX license identifier from its installed `package.json` and the verbatim text from its shipped LICENSE / COPYING / NOTICE file when present.');
lines.push('- Sorts entries alphabetically and groups them by SPDX identifier in the summary table.');
lines.push('');
lines.push('### Manual overrides applied');
lines.push('');
lines.push('- `@openai/realtime-api-beta` is installed directly from a GitHub tarball with `"private": true` in its `package.json`, which causes `license-checker` to report it as `UNLICENSED`. Its repository declares `"license": "MIT"` and ships a standard MIT LICENSE file (`Copyright (c) 2024 OpenAI`). The generator records it as MIT and includes the verbatim license text below.');
lines.push('- The EpicStaff frontend project itself (`frontend-crewai`) is filtered out of the list — this notices file only covers third-party code.');
lines.push('');

const md = lines.join('\n');
fs.writeFileSync(OUTPUT_FILE, md, 'utf8');
process.stderr.write('Discovered ' + entries.length + ' third-party packages.\nWrote ' + OUTPUT_FILE + '\n');
