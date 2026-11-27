// Run with: node --test scripts/check-image-licenses.test.mjs
import assert from 'node:assert/strict';
import test from 'node:test';

import { findProblems, loadPolicy } from './check-image-licenses.mjs';

const policy = {
  allowed: new Set(['GPL-2.0-or-later', 'MIT']),
  reviewedSourcePackages: { 'gcc-12': 'MIT', 'python3.11': 'MIT' },
};

const report = (packages) => ({ ArtifactName: 'image', Results: [{ Class: 'os-pkgs', Packages: packages }] });

test('allowed licences pass, others are named', () => {
  const problems = findProblems(
    report([
      { Name: 'bash', Version: '5.2', Licenses: ['GPL-2.0-or-later', 'MIT'] },
      { Name: 'redis-tools', Version: '8', Licenses: ['MIT', 'SSPL-1.0'] },
    ]),
    policy
  );
  assert.deepEqual(problems, ['image: redis-tools@8: licence "SSPL-1.0" is not in scripts/os-license-policy.json']);
});

test('a licence Trivy cannot name comes from a reviewed source package, else fails', () => {
  const problems = findProblems(
    report([
      { Name: 'libgcc-s1', Version: '12', SrcName: 'gcc-12' },
      { Name: 'python3.11-minimal', Version: '3.11', SrcName: 'python3.11', Licenses: ['text://Permission to use'] },
      { Name: 'ngrok', Version: '3', Licenses: [] },
      { Name: 'constructor', Version: '1', SrcName: 'constructor' },
      { Name: 'libsasl2-2', Version: '2', SrcName: 'cyrus-sasl2', Licenses: ['MIT', 'text://IBM-as-is'] },
    ]),
    policy
  );
  assert.deepEqual(problems, [
    'image: ngrok@3: no licence found (source package "ngrok")',
    'image: constructor@1: no licence found (source package "constructor")',
    'image: libsasl2-2@2: custom licence text Trivy cannot name (source package "cyrus-sasl2")',
  ]);
});

test('a reviewed source package does not hide a named licence outside the policy', () => {
  const problems = findProblems(report([{ Name: 'libgcc-s1', Version: '12', SrcName: 'gcc-12', Licenses: ['SSPL-1.0'] }]), policy);
  assert.deepEqual(problems, ['image: libgcc-s1@12: licence "SSPL-1.0" is not in scripts/os-license-policy.json']);
});

test('a report without OS packages is a problem, not a pass', () => {
  assert.match(findProblems({ ArtifactName: 'image', Results: [] }, policy)[0], /no OS packages found/);
});

test('every reviewed source package licence is itself allowed', () => {
  const { allowed, reviewedSourcePackages } = loadPolicy();
  for (const [source, license] of Object.entries(reviewedSourcePackages)) {
    assert.ok(allowed.has(license), `${source}: "${license}" is not in "allowed"`);
  }
});
