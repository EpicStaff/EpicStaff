// Run with: node --test scripts/check-licenses.test.mjs
import assert from 'node:assert/strict';
import test from 'node:test';

import { findProblems, packageRows } from './check-licenses.mjs';
import { licenseProblem, toSpdxExpression } from './license-policy.mjs';

test('allowed licences pass, unreviewed ones are named', () => {
  assert.equal(licenseProblem('MIT'), null);
  assert.equal(licenseProblem('(MIT OR GPL-3.0-or-later)'), null);
  assert.match(licenseProblem('GPL-3.0-or-later'), /only as an alternative/);
  assert.match(licenseProblem('MIT AND AGPL-3.0-only'), /"AGPL-3.0-only"/);
  assert.match(licenseProblem('BSD License'), /not a valid SPDX expression/);
});

test('pip-licenses classifier names become SPDX, several are read as AND', () => {
  assert.equal(toSpdxExpression('MIT License'), 'MIT');
  assert.equal(toSpdxExpression('3-Clause BSD License'), 'BSD-3-Clause');
  assert.equal(toSpdxExpression('Apache Software License; MIT License'), '(Apache-2.0) AND (MIT)');
  assert.equal(toSpdxExpression('BSD 3-Clause OR Apache-2.0'), 'BSD-3-Clause OR Apache-2.0');
});

const notices = [
  '<!-- BEGIN GENERATED: frontend -->',
  '| Package | Version | License |',
  '| `@angular/core` | 22.0.0 | MIT |',
  '<!-- END GENERATED: frontend -->',
  '| `outside-any-region` | 1.0 | AGPL-3.0-only |',
  '<!-- BEGIN GENERATED: backend -->',
  '| `pkg-a` | 1.0 | Apache Software License; MIT License | Copyright \\| A |',
  '| `pkg-b` | 2.0 | AGPL-3.0-only |  |',
  '<!-- END GENERATED: backend -->',
].join('\n');

test('reads package rows of both regions only', () => {
  const rows = packageRows(notices);
  assert.deepEqual(rows.frontend, [{ name: '@angular/core', version: '22.0.0', license: 'MIT' }]);
  assert.deepEqual(rows.backend.map((row) => row.name), ['pkg-a', 'pkg-b']);
});

test('reports each unacceptable package and an empty region', () => {
  assert.deepEqual(findProblems(notices), [
    'backend: pkg-b@2.0: licence "AGPL-3.0-only" uses "AGPL-3.0-only", not in scripts/license-policy.json',
  ]);
  const noFrontend = notices.replace('| `@angular/core` | 22.0.0 | MIT |', '');
  assert.match(findProblems(noFrontend)[0], /^frontend: no packages found/);
});
