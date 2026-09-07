#!/usr/bin/env node
/**
 * CI regression guard: fail when frontend source imports a package that
 * package.json does not declare.
 *
 * Context: EST-3802. Three packages — uuid, jsonc-parser and @types/json-schema —
 * were imported by src/ while absent from package.json, resolving only by accident
 * through orphaned lockfile entries and transitive devDependencies. A clean install
 * or the removal of an unrelated toolchain package silently broke the build. A grep
 * missed two of the three; this script does not.
 *
 * Usage:  node scripts/check-undeclared-imports.mjs
 * Exit codes: 0 = clean, 1 = undeclared imports found.
 */

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { builtinModules } from 'node:module';

const repoRoot = join(fileURLToPath(import.meta.url), '..', '..');
const workspace = join(repoRoot, 'frontend');
const srcRoot = join(workspace, 'src');

if (!existsSync(srcRoot)) {
  console.error(`Undeclared import check FAILED: ${relative(repoRoot, srcRoot)} does not exist.`);
  process.exit(1);
}

const pkg = JSON.parse(readFileSync(join(workspace, 'package.json'), 'utf8').replace(/^﻿/, ''));
const declared = new Set([
  ...Object.keys(pkg.dependencies ?? {}),
  ...Object.keys(pkg.devDependencies ?? {}),
]);

// tsconfig `paths` aliases and anything rooted at baseUrl resolve locally, not from node_modules.
const tsconfig = readFileSync(join(workspace, 'tsconfig.json'), 'utf8');
const aliases = [...tsconfig.matchAll(/"(@[\w-]+\/[\w-]+)":\s*\[/g)].map((m) => m[1]);
const baseUrlRoots = ['src/', 'environments/'];
const builtins = new Set(builtinModules);

// Only line-anchored import/export statements and dynamic import(). A looser search for
// `from` also matches the word inside ordinary strings and template literals.
const PATTERNS = [
  /^[ \t]*(?:import|export)\s[^;]*?\sfrom\s*['"]([^'"\n]+)['"]/gm,
  /^[ \t]*import\s*['"]([^'"\n]+)['"]/gm,
  /\bimport\s*\(\s*['"]([^'"\n]+)['"]\s*\)/g,
];

const files = [];
(function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full);
    else if (entry.endsWith('.ts')) files.push(full);
  }
})(srcRoot);

const findings = new Map();

for (const file of files) {
  const source = readFileSync(file, 'utf8');
  for (const pattern of PATTERNS) {
    for (const match of source.matchAll(pattern)) {
      const spec = match[1];
      if (spec.startsWith('.') || spec.startsWith('/')) continue;
      if (baseUrlRoots.some((root) => spec.startsWith(root))) continue;
      if (aliases.some((alias) => spec === alias || spec.startsWith(`${alias}/`))) continue;

      const scope = spec.startsWith('@') ? spec.split('/').slice(0, 2).join('/') : spec.split('/')[0];
      // A type-only import of `foo` is satisfied by `@types/foo`, and of `@scope/foo` by `@types/scope__foo`.
      const typesAlias = scope.startsWith('@')
        ? `@types/${scope.slice(1).replace('/', '__')}`
        : `@types/${scope}`;
      if (declared.has(scope) || declared.has(typesAlias) || builtins.has(scope)) continue;

      const line = source.slice(0, match.index).split('\n').length;
      if (!findings.has(scope)) findings.set(scope, []);
      findings.get(scope).push(`${relative(repoRoot, file).split(sep).join('/')}:${line}`);
    }
  }
}

if (findings.size > 0) {
  const total = [...findings.values()].reduce((n, sites) => n + sites.length, 0);
  console.error(
    `Undeclared import check FAILED: ${findings.size} package(s), ${total} import site(s).\n` +
      'Each package below is imported by frontend/src but missing from frontend/package.json,\n' +
      'so it resolves only by accident and will break on a clean install. Declare it\n' +
      'explicitly (in dependencies if it ships to the browser), or replace the import.\n'
  );
  for (const [scope, sites] of [...findings].sort()) {
    console.error(`  ${scope}`);
    for (const site of [...new Set(sites)].sort()) console.error(`      ${site}`);
  }
  process.exit(1);
}

console.log(
  `Undeclared import check passed: ${files.length} files scanned, every bare import is declared.`
);
