/**
 * Licence policy for shipped third-party code: decides whether a package's
 * licence lets us ship it under the EpicStaff licence.
 *
 * The lists live in scripts/license-policy.json:
 *   allowed          SPDX identifiers a package may be shipped under on their own.
 *   alternativeOnly  reviewed, but acceptable only as one side of an OR whose
 *                    other side is allowed, e.g. "(MIT OR GPL-3.0-or-later)".
 *   exceptions       reviewed SPDX licence exceptions (the part after WITH).
 * An identifier in neither list is unreviewed and always a problem: check the
 * licence's terms, then add it to the matching list in the same change.
 *
 * Used by frontend/scripts/generate-third-party-notices.mjs (refuses to write
 * notices for an unacceptable package) and scripts/check-licenses.mjs (checks
 * every package listed in THIRD-PARTY-NOTICES.md, frontend and backend).
 */

import fs from 'node:fs';

const policy = JSON.parse(fs.readFileSync(new URL('./license-policy.json', import.meta.url), 'utf8'));
const ALLOWED = new Set(policy.allowed);
const ALTERNATIVE_ONLY = new Set(policy.alternativeOnly);
const EXCEPTIONS = new Set(policy.exceptions);

// pip-licenses reports Python trove classifier names, not SPDX identifiers.
// Only names that map to exactly one SPDX identifier are listed: "BSD License"
// (2- or 3-clause?) and "GNU Library or Lesser General Public License (LGPL)"
// (which version?) are left out on purpose, so they reach a person, who pins
// the package in SPDX_OVERRIDES in scripts/generate-python-notices.py.
const CLASSIFIER_ALIASES = {
  'Mozilla Public License 2.0 (MPL 2.0)': 'MPL-2.0',
  'Python Software Foundation License': 'PSF-2.0',
  'The Unlicense (Unlicense)': 'Unlicense',
  'Apache Software License': 'Apache-2.0',
  'ISC License (ISCL)': 'ISC',
  '3-Clause BSD License': 'BSD-3-Clause',
  'Apache License 2.0': 'Apache-2.0',
  'BSD 3-Clause': 'BSD-3-Clause',
  'MIT License': 'MIT',
  'Apache 2.0': 'Apache-2.0',
};
// Longest first, so "3-Clause BSD License" is not half-replaced by a shorter name.
const ALIAS_NAMES = Object.keys(CLASSIFIER_ALIASES).sort((left, right) => right.length - left.length);

// Turns a licence string as pip-licenses writes it into an SPDX expression.
// pip-licenses joins several classifiers with "; ". Whether that means "pick
// one" or "parts under each" is not recorded, so it is read as AND: a wrong
// guess then flags a package for review instead of letting it through.
export function toSpdxExpression(raw) {
  let expression = raw;
  for (const name of ALIAS_NAMES) expression = expression.split(name).join(CLASSIFIER_ALIASES[name]);
  const parts = expression.split(';').map((part) => part.trim());
  return parts.length === 1 ? parts[0] : parts.map((part) => `(${part})`).join(' AND ');
}

class LicenseExpressionError extends Error {}

// Parses an SPDX licence expression (SPDX specification, annex D):
//   expression := and ('OR' and)*
//   and        := term ('AND' term)*
//   term       := '(' expression ')' | identifier ['+'] ['WITH' exception]
// and returns a tree of { kind: 'or' | 'and', parts } and
// { kind: 'license', identifier, exception } nodes.
function parseLicenseExpression(expression) {
  const tokens = expression.match(/\(|\)|[^\s()]+/g) || [];
  let position = 0;
  const peek = () => tokens[position];
  const take = () => tokens[position++];
  const isIdentifier = (token) => token !== undefined && /^[A-Za-z0-9.-]+\+?$/.test(token) && !/^(AND|OR|WITH)$/.test(token);

  function parseTerm() {
    if (peek() === '(') {
      take();
      const inner = parseOr();
      if (take() !== ')') throw new LicenseExpressionError();
      return inner;
    }
    const token = take();
    if (!isIdentifier(token)) throw new LicenseExpressionError();
    const node = { kind: 'license', identifier: token.replace(/\+$/, ''), exception: null };
    if (peek() === 'WITH') {
      take();
      const exception = take();
      if (!isIdentifier(exception) || exception.endsWith('+')) throw new LicenseExpressionError();
      node.exception = exception;
    }
    return node;
  }
  function parseSequence(operator, parsePart, kind) {
    const parts = [parsePart()];
    while (peek() === operator) {
      take();
      parts.push(parsePart());
    }
    return parts.length === 1 ? parts[0] : { kind, parts };
  }
  const parseAnd = () => parseSequence('AND', parseTerm, 'and');
  const parseOr = () => parseSequence('OR', parseAnd, 'or');

  const tree = parseOr();
  if (position !== tokens.length) throw new LicenseExpressionError();
  return tree;
}

// Returns why the SPDX expression may not be shipped, or null when it may.
export function licenseProblem(expression) {
  let tree;
  try {
    tree = parseLicenseExpression(expression);
  } catch (error) {
    if (error instanceof LicenseExpressionError) return 'is not a valid SPDX expression';
    throw error;
  }
  const unreviewed = [];
  // True when the terms can be met using allowed licences only.
  function acceptable(node) {
    if (node.kind === 'or') return node.parts.map(acceptable).some(Boolean);
    if (node.kind === 'and') return node.parts.map(acceptable).every(Boolean);
    if (!ALLOWED.has(node.identifier) && !ALTERNATIVE_ONLY.has(node.identifier)) unreviewed.push(node.identifier);
    if (node.exception !== null && !EXCEPTIONS.has(node.exception)) unreviewed.push(node.exception);
    return ALLOWED.has(node.identifier) && (node.exception === null || EXCEPTIONS.has(node.exception));
  }
  const ok = acceptable(tree);
  if (unreviewed.length > 0) {
    return `uses ${unreviewed.map((identifier) => `"${identifier}"`).join(', ')}, not in scripts/license-policy.json`;
  }
  if (!ok) return 'can only be met under a licence that is acceptable only as an alternative';
  return null;
}
