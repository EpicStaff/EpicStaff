// Run with: node --test scripts/check-licenses.test.mjs
import assert from 'node:assert/strict';
import test from 'node:test';

import { findProblems, packageRows } from './check-licenses.mjs';
import { licenseProblem, toSpdxExpression } from './license-policy.mjs';

test('allowed licences pass, unreviewed ones are named', () => {
  assert.equal(licenseProblem('MIT'), null);
  assert.equal(licenseProblem('(MIT OR GPL-3.0-or-later)'), null);
  assert.match(licenseProblem('GPL-3.0-or-later'), /only as an alternative/);
  assert.match(licenseProblem('MIT AND SSPL-1.0'), /"SSPL-1.0"/);
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
  '| `outside-any-region` | 1.0 | SSPL-1.0 |',
  '<!-- BEGIN GENERATED: backend -->',
  '| `pkg-a` | 1.0 | Apache Software License; MIT License | Copyright \\| A |',
  '| `pkg-b` | 2.0 | SSPL-1.0 |  |',
  '<!-- END GENERATED: backend -->',
].join('\n');

test('reads package rows of both regions only', () => {
  const rows = packageRows(notices);
  assert.deepEqual(rows.frontend, [{ name: '@angular/core', version: '22.0.0', license: 'MIT' }]);
  assert.deepEqual(rows.backend.map((row) => row.name), ['pkg-a', 'pkg-b']);
});

test('reports each unacceptable package and an empty region', () => {
  assert.deepEqual(findProblems(notices), [
    'backend: pkg-b@2.0: licence "SSPL-1.0" uses "SSPL-1.0", not in scripts/license-policy.json',
  ]);
  const noFrontend = notices.replace('| `@angular/core` | 22.0.0 | MIT |', '');
  assert.match(findProblems(noFrontend)[0], /^frontend: no packages found/);
});
