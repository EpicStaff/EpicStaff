#!/usr/bin/env node
/**
 * Regenerates the `frontend` region of THIRD-PARTY-NOTICES.md in the
 * repository root.
 *
 * Scope: production npm dependencies of the EpicStaff frontend
 * (declared in frontend/package.json dependencies, resolved via
 * frontend/package-lock.json).
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
 * Needs `npm ci` first and nothing else: the package list comes from
 * package-lock.json and each installed package's own package.json, so no
 * third-party tool is downloaded or run.
 *
 * Every package must declare its licence in package.json as an SPDX
 * expression built from REVIEWED_LICENSE_IDS. Anything else (no licence, a
 * non-SPDX value such as "BSD", or an identifier nobody has reviewed yet)
 * stops the script with the package named, so the licence is checked by a
 * person instead of being guessed from LICENSE or README text.
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

const REGION = 'frontend';
const BEGIN_MARKER = `<!-- BEGIN GENERATED: ${REGION} -->`;
const END_MARKER = `<!-- END GENERATED: ${REGION} -->`;

// SPDX licence identifiers that have been reviewed for the shipped frontend.
// A package declaring any other identifier stops the script: check that
// licence's terms, then add its identifier here in the same change.
const REVIEWED_LICENSE_IDS = new Set([
  '0BSD',
  'Apache-2.0',
  'BSD-2-Clause',
  'GPL-3.0-or-later',
  'ISC',
  'MIT',
  'MPL-2.0',
  'OFL-1.1',
  'Zlib',
]);

// Accepts an SPDX expression ("MIT", "(MIT OR Apache-2.0)", "GPL-2.0-only WITH
// Classpath-exception-2.0") whose licence identifiers are all reviewed, and
// returns the reason it is rejected otherwise.
function licenseProblem(expression) {
  const tokens = expression.match(/\(|\)|[^\s()]+/g) || [];
  let depth = 0;
  let expectOperand = true;
  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index];
    if (token === '(') {
      if (!expectOperand) return 'is not a valid SPDX expression';
      depth++;
    } else if (token === ')') {
      if (expectOperand || depth === 0) return 'is not a valid SPDX expression';
      depth--;
    } else if (token === 'AND' || token === 'OR') {
      if (expectOperand) return 'is not a valid SPDX expression';
      expectOperand = true;
    } else if (token === 'WITH') {
      // The exception names a licence exception, not a licence; it must follow one.
      const exception = tokens[index + 1];
      if (expectOperand || !exception || /^(AND|OR|WITH|\(|\))$/.test(exception)) {
        return 'is not a valid SPDX expression';
      }
      index++;
    } else {
      if (!expectOperand) return 'is not a valid SPDX expression';
      const identifier = token.replace(/\+$/, '');
      if (!REVIEWED_LICENSE_IDS.has(identifier)) {
        return `uses "${identifier}", which is not in REVIEWED_LICENSE_IDS`;
      }
      expectOperand = false;
    }
  }
  if (expectOperand || depth !== 0) return 'is not a valid SPDX expression';
  return null;
}

function declaredLicenses(manifest) {
  const declared = manifest.license ?? manifest.licenses;
  const list = (Array.isArray(declared) ? declared : [declared])
    .map((entry) => (entry && typeof entry === 'object' ? entry.type || entry.name : entry))
    .filter((entry) => typeof entry === 'string' && entry.trim() !== '');
  if (list.length === 0) return { problem: 'declares no licence in package.json' };
  for (const expression of list) {
    const problem = licenseProblem(expression);
    if (problem) return { problem: `licence "${expression}" ${problem}` };
  }
  return { licenses: list.length === 1 ? list[0] : list };
}

// The file that carries a package's licence, in this order of precedence on the
// upper-cased name without its extension: LICENSE, LICENSE-*, LICENCE,
// LICENCE-*, COPYING, README. A README is only a last resort; the notices below
// print its text only when the name says it is a licence.
const LICENSE_FILE_PRECEDENCE = [/^LICENSE$/, /^LICENSE-\w+$/, /^LICENCE$/, /^LICENCE-\w+$/, /^COPYING$/, /^README$/];

function licenseFileOf(packageDir) {
  const files = fs.readdirSync(packageDir);
  for (const pattern of LICENSE_FILE_PRECEDENCE) {
    const match = files.find((file) => pattern.test(path.basename(file, path.extname(file)).toUpperCase()));
    if (match && fs.lstatSync(path.join(packageDir, match)).isFile()) return path.join(packageDir, match);
  }
  return null;
}

// npm writes repository URLs in several shapes ("user/repo", "github:user/repo",
// "git://…", "git+ssh://…"). For the hosts npm recognises they are normalised the
// way npm normalises package.json, then reduced to a browsable URL.
const SHORTCUT_HOSTS = { github: 'github.com', gitlab: 'gitlab.com', bitbucket: 'bitbucket.org' };
const KNOWN_GIT_HOSTS = new Set(Object.values(SHORTCUT_HOSTS));

function normalizeRepositoryUrl(url) {
  const shortcut = /^(?:(github|gitlab|bitbucket):)?([\w.-]+)\/([\w.-]+?)(?:\.git)?(?:#.*)?$/.exec(url);
  if (shortcut && !url.includes('://')) {
    return `git+https://${SHORTCUT_HOSTS[shortcut[1] || 'github']}/${shortcut[2]}/${shortcut[3]}.git`;
  }
  const scpLike = /^git@([^:/]+):([^/]+)\/(.+?)(?:\.git)?(?:#.*)?$/.exec(url);
  if (scpLike && KNOWN_GIT_HOSTS.has(scpLike[1])) return `git@${scpLike[1]}:${scpLike[2]}/${scpLike[3]}.git`;
  const full = /^(git\+ssh|git\+https|https?|git):\/\/(?:[^@/]+@)?([^/:]+)(?::\d+)?\/([^/]+)\/(.+?)(?:\.git)?\/?(?:#.*)?$/.exec(url);
  if (!full || !KNOWN_GIT_HOSTS.has(full[2])) return url;
  const [, protocol, host, owner, project] = full;
  if (protocol === 'git') return `git://${host}/${owner}/${project}.git`;
  if (protocol === 'git+ssh') return `git+ssh://git@${host}/${owner}/${project}.git`;
  return `git+https://${host}/${owner}/${project}.git`;
}

function repositoryOf(manifest) {
  const raw = typeof manifest.repository === 'string' ? manifest.repository : manifest.repository?.url;
  if (typeof raw !== 'string') return null;
  return normalizeRepositoryUrl(raw)
    .replace('git+ssh://git@', 'git://')
    .replace('git+https://github.com', 'https://github.com')
    .replace('git://github.com', 'https://github.com')
    .replace('git@github.com:', 'https://github.com/')
    .replace(/\.git$/, '');
}

// npm accepts an author as an object or as the string "Name <email> (url)".
function authorOf(manifest) {
  const author = manifest.author;
  if (author && typeof author === 'object') return author;
  if (typeof author !== 'string') return {};
  const match = /^([^<(]+?)?[ \t]*(?:<([^>(]+?)>)?[ \t]*(?:\(([^)]+?)\)|$)/.exec(author);
  return match ? { name: match[1], email: match[2], url: match[3] } : {};
}

// The production tree is every package-lock.json entry npm does not mark
// `dev`. An entry with no directory under node_modules is an optional package
// for another platform, which is not installed and not shipped from here.
const lockFile = path.join(FRONTEND_DIR, 'package-lock.json');
if (!fs.existsSync(lockFile)) {
  process.stderr.write(`Error: ${lockFile} does not exist.\n`);
  process.exit(1);
}
const lockedPackages = JSON.parse(fs.readFileSync(lockFile, 'utf8')).packages || {};
if (!fs.existsSync(path.join(FRONTEND_DIR, 'node_modules'))) {
  process.stderr.write('Error: frontend/node_modules does not exist. Run `npm ci` first.\n');
  process.exit(1);
}

// Each installed production package once, keyed name@version.
const data = {};
const licenseProblems = [];
for (const [location, entry] of Object.entries(lockedPackages)) {
  if (location === '' || entry.dev || entry.link) continue;
  const packageDir = path.join(FRONTEND_DIR, location);
  const manifestFile = path.join(packageDir, 'package.json');
  if (!fs.existsSync(manifestFile)) {
    if (entry.optional) continue;
    process.stderr.write(`Error: ${location} is in package-lock.json but not installed. Run \`npm ci\` first.\n`);
    process.exit(1);
  }
  const manifest = JSON.parse(fs.readFileSync(manifestFile, 'utf8'));
  const key = `${manifest.name}@${manifest.version}`;
  if (data[key]) continue;
  const { licenses, problem } = declaredLicenses(manifest);
  if (problem) licenseProblems.push(`  ${key}: ${problem}`);
  const author = authorOf(manifest);
  data[key] = {
    licenses,
    repository: repositoryOf(manifest),
    publisher: author.name,
    email: author.email,
    url: author.url,
    licenseFile: licenseFileOf(packageDir),
  };
}
if (licenseProblems.length > 0) {
  process.stderr.write(
    'Error: these production packages need their licence reviewed by hand:\n' +
      [...new Set(licenseProblems)].sort().join('\n') +
      '\nCheck each licence. If its terms are acceptable, add its SPDX identifier to ' +
      'REVIEWED_LICENSE_IDS; otherwise remove the package. THIRD-PARTY-NOTICES.md was not changed.\n'
  );
  process.exit(1);
}

// Build entries
const entries = [];
for (const key of Object.keys(data).sort()) {
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
lines.push('Production npm dependencies of the Angular frontend. Backend Python packages are counted separately under "Backend (Python)".');
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
lines.push('Third-party code copied into this repository rather than installed as a dependency. It is not in `package-lock.json`, so these entries are maintained by hand in the generator.');
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

const body = lines.join('\n');

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
