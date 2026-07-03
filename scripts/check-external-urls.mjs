#!/usr/bin/env node
/**
 * CI regression guard: fail when a runtime CDN / external font URL reference
 * is (re)introduced into the frontend source tree.
 *
 * Context: EST-3245 removed all runtime CDN dependencies (Google Fonts,
 * jsDelivr, Tabler icons CDN). This script keeps them from coming back.
 *
 * Usage:  node scripts/check-external-urls.mjs
 * Exit codes: 0 = clean, 1 = violations found.
 *
 * Allowlist: scripts/external-url-allowlist.txt — one substring per line,
 * `#` starts a comment. A matched line is skipped if it contains any
 * allowlisted substring.
 */

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = join(fileURLToPath(import.meta.url), '..', '..');

// Denylist of CDN / font-hosting domains that must never appear in runtime source.
const DENY_PATTERNS = [
  /fonts\.googleapis\.com/i,
  /fonts\.gstatic\.com/i,
  /cdn\.jsdelivr\.net/i,
  /cdnjs\.cloudflare\.com/i,
  /unpkg\.com/i,
  /use\.fontawesome\.com/i,
  /use\.typekit\.net/i,
  /https?:\/\/cdn\./i, // generic cdn.* hosts
];

// Files / directory subtrees to scan (relative to repo root).
const SCAN_FILES = ['frontend/src/index.html', 'frontend/angular.json'];
const SCAN_DIRS = ['frontend/src'];
const SCAN_EXTENSIONS = new Set(['.scss', '.css', '.html', '.ts']);

// Prebuilt widget files that can realistically (re)introduce a runtime CDN
// dependency: embed.js injects <script>/<link> tags, styles.css can
// @import / url() remote fonts. For these files ANY external https?:// URL
// inside url(...) or @import is also a violation, not just the named CDN
// domains. main.js / polyfills.js are deliberately NOT scanned — minified
// bundles full of benign doc-comment domains.
const WIDGET_FILES = [
  'frontend/public/epicchat-widget/embed.js',
  'frontend/public/epicchat-widget/styles.css',
];
const WIDGET_EXTRA_PATTERNS = [
  /@import\s+(?:url\(\s*)?["']?https?:\/\//i,
  /url\(\s*["']?https?:\/\//i,
];

// Prebuilt bundles and third-party trees are excluded — they may contain
// benign doc-comment domains and are not authored source.
const EXCLUDED_DIR_NAMES = new Set(['node_modules', '.git', 'dist']);

function loadAllowlist() {
  const allowlistPath = join(repoRoot, 'scripts', 'external-url-allowlist.txt');
  if (!existsSync(allowlistPath)) return [];
  return readFileSync(allowlistPath, 'utf8')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'));
}

function collectFiles(dir, out) {
  for (const entry of readdirSync(dir)) {
    if (EXCLUDED_DIR_NAMES.has(entry)) continue;
    const full = join(dir, entry);
    const stats = statSync(full);
    if (stats.isDirectory()) {
      collectFiles(full, out);
    } else {
      const dot = entry.lastIndexOf('.');
      if (dot !== -1 && SCAN_EXTENSIONS.has(entry.slice(dot))) out.add(full);
    }
  }
}

const allowlist = loadAllowlist();
const files = new Set();
const widgetFiles = new Set();

for (const rel of SCAN_FILES) {
  const full = join(repoRoot, rel);
  if (existsSync(full)) files.add(full);
}
for (const rel of SCAN_DIRS) {
  const full = join(repoRoot, rel);
  if (existsSync(full)) collectFiles(full, files);
}
for (const rel of WIDGET_FILES) {
  const full = join(repoRoot, rel);
  if (existsSync(full)) {
    files.add(full);
    widgetFiles.add(full);
  }
}

const violations = [];

for (const file of files) {
  const patterns = widgetFiles.has(file)
    ? [...DENY_PATTERNS, ...WIDGET_EXTRA_PATTERNS]
    : DENY_PATTERNS;
  const lines = readFileSync(file, 'utf8').split(/\r?\n/);
  lines.forEach((line, index) => {
    const pattern = patterns.find((re) => re.test(line));
    if (!pattern) return;
    if (allowlist.some((allowed) => line.includes(allowed))) return;
    violations.push({
      file: relative(repoRoot, file).split(sep).join('/'),
      line: index + 1,
      pattern: pattern.source,
      text: line.trim().slice(0, 200),
    });
  });
}

if (violations.length > 0) {
  console.error(
    `External CDN URL check FAILED: ${violations.length} violation(s) found.\n` +
      'Runtime CDN references were removed in EST-3245 and must not be reintroduced.\n' +
      'Vendor the asset locally instead, or (for benign non-runtime hits) add a\n' +
      'substring to scripts/external-url-allowlist.txt.\n'
  );
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line}  [${v.pattern}]  ${v.text}`);
  }
  process.exit(1);
}

console.log(`External CDN URL check passed: ${files.size} files scanned, no denylisted URLs found.`);
