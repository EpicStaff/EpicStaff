#!/usr/bin/env node
/**
 * Fails when an OS package inside a shipped Docker image is under a licence
 * that scripts/os-license-policy.json does not list.
 *
 * Input: Trivy JSON reports, one per image, written by
 *   trivy image --scanners license --pkg-types os --format json --output <file> <image>
 * Only distro packages (dpkg, apk) are covered. Python and npm packages are
 * checked by scripts/check-licenses.mjs against scripts/license-policy.json,
 * and software a base image installs outside its package manager (the
 * interpreter in python:*-slim, for one) is invisible to this scan.
 *
 * Why a policy of its own: OS packages are separate programs shipped next to
 * EpicStaff in the same image, not linked into it, so GPL system tools that
 * scripts/license-policy.json rejects for our dependencies are acceptable here.
 * Trivy reports licence names as Debian copyright files spell them, many of
 * them not SPDX, so names are matched exactly rather than parsed.
 *
 * os-license-policy.json:
 *   allowed                 licence names an OS package may be shipped under.
 *   reviewedSourcePackages  source package -> its licence, set after reading
 *                           its copyright file by hand. Used only where Trivy
 *                           cannot name a licence: none found, or a custom
 *                           text it reports as "text://<first line>".
 *
 * Usage:  node scripts/check-image-licenses.mjs report.json [report.json ...]
 * Exit codes: 0 = every package acceptable, 1 = a problem (listed on stdout).
 */

import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const POLICY_URL = new URL('./os-license-policy.json', import.meta.url);

export function loadPolicy(policyUrl = POLICY_URL) {
  const policy = JSON.parse(fs.readFileSync(policyUrl, 'utf8'));
  return { allowed: new Set(policy.allowed), reviewedSourcePackages: policy.reviewedSourcePackages };
}

const CUSTOM_TEXT = 'text://';

export function findProblems(report, policy) {
  const image = report.ArtifactName;
  const packages = (report.Results ?? [])
    .filter((result) => result.Class === 'os-pkgs')
    .flatMap((result) => result.Packages ?? []);
  // Every image we ship has a distribution; none found means Trivy could not read it, not that it is clean.
  if (packages.length === 0) return [`${image}: no OS packages found -- did Trivy fail to detect the distribution?`];

  const problems = [];
  for (const { Name: name, Version: version, SrcName: sourceName, Licenses: found } of packages) {
    const source = sourceName ?? name;
    const all = [...new Set(found ?? [])];
    const named = all.filter((license) => !license.startsWith(CUSTOM_TEXT));
    const unnamed = all.length === 0 || named.length < all.length;
    const licenses = [...named];
    if (unnamed && Object.hasOwn(policy.reviewedSourcePackages, source)) {
      licenses.push(policy.reviewedSourcePackages[source]);
    } else if (all.length === 0) {
      problems.push(`${image}: ${name}@${version}: no licence found (source package "${source}")`);
    } else if (unnamed) {
      problems.push(`${image}: ${name}@${version}: custom licence text Trivy cannot name (source package "${source}")`);
    }
    for (const license of licenses) {
      if (!policy.allowed.has(license)) {
        problems.push(`${image}: ${name}@${version}: licence "${license}" is not in scripts/os-license-policy.json`);
      }
    }
  }
  return problems;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const reportPaths = process.argv.slice(2);
  if (reportPaths.length === 0) {
    console.log('Usage: node scripts/check-image-licenses.mjs report.json [report.json ...]');
    process.exit(1);
  }
  const policy = loadPolicy();
  const problems = reportPaths.flatMap((path) => findProblems(JSON.parse(fs.readFileSync(path, 'utf8')), policy));
  if (problems.length === 0) {
    console.log(`Every OS package in ${reportPaths.length} image(s) has an acceptable licence.`);
    process.exit(0);
  }
  console.log(`${problems.length} OS package licence(s) need review:\n`);
  console.log(problems.join('\n'));
  console.log(
    '\nRead the package\'s copyright file (/usr/share/doc/<package>/copyright in the image). If its ' +
      'terms are acceptable, add the licence name to "allowed" in scripts/os-license-policy.json, or, ' +
      'when Trivy could not name the licence, the source package to "reviewedSourcePackages"; otherwise remove ' +
      'the package from the image.'
  );
  process.exit(1);
}
