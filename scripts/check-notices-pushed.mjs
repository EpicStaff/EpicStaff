#!/usr/bin/env node
/**
 * pre-push gate: THIRD-PARTY-NOTICES.md must match frontend/package-lock.json at
 * the tip of every branch being pushed.
 *
 * Companion to check-third-party-notices.mjs, which enforces the same rule in CI.
 * The two cannot share one implementation, and the difference is the whole point:
 *
 *   - CI runs after a clean checkout, so the working tree *is* the commit. Hashing
 *     files from disk is correct there.
 *   - pre-push runs against a working tree that routinely disagrees with what is
 *     being pushed — uncommitted edits, a stash, commits pulled from someone else.
 *     Reading from disk lets a bad commit through whenever the disk happens to be
 *     clean, which is how ef183c582 was pushed with a lockfile its notices did not
 *     cover: the tree had been reverted, the commit had not.
 *
 * So this reads both files out of the commit object via `git show <sha>:<path>`.
 *
 * Only the tip is judged, matching what CI sees. Intermediate commits may be
 * inconsistent on purpose — committing the lockfile and the regenerated notices
 * separately is a normal thing to do, and a single follow-up commit fixes the tip
 * without rewriting history.
 *
 * Line endings are safe to compare this way: .gitattributes normalises to LF in
 * the index, and package-lock.json holds no CRLF in either the blob or the working
 * copy, so a blob hash equals the hash the generator stamped from disk.
 *
 * Ref lines arrive on stdin as `local_ref local_sha remote_ref remote_sha`.
 * A local_sha of all zeroes means a branch deletion and is ignored.
 *
 * Usage: node scripts/check-notices-pushed.mjs   (stdin from git)
 * Exit codes: 0 = every pushed tip is consistent, 1 = at least one is not.
 */

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const LOCK = 'frontend/package-lock.json';
const NOTICES = 'THIRD-PARTY-NOTICES.md';
const ZERO = /^0+$/;

const repoRoot = join(fileURLToPath(import.meta.url), '..', '..');

const git = (args, encoding = 'utf8') =>
    execFileSync('git', args, { cwd: repoRoot, encoding, maxBuffer: 256 * 1024 * 1024 });

const blobAt = (sha, path) => {
    try {
        return git(['show', `${sha}:${path}`], 'buffer');
    } catch {
        return null;
    }
};

let stdin = '';
try {
    stdin = readFileSync(0, 'utf8');
} catch {
    stdin = '';
}

const refs = stdin
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

// Invoked outside a push, or nothing to push: say nothing.
if (refs.length === 0) process.exit(0);

const problems = [];

for (const line of refs) {
    const [localRef, localSha] = line.split(/\s+/);
    if (!localSha || ZERO.test(localSha)) continue; // branch deletion

    const lockBuf = blobAt(localSha, LOCK);
    const noticesBuf = blobAt(localSha, NOTICES);
    if (!lockBuf || !noticesBuf) continue;

    const stamped = noticesBuf
        .toString('utf8')
        .match(/<!-- package-lock\.json sha256: ([0-9a-f]+|no-lock) -->/)?.[1];
    if (!stamped) continue;

    const actual = createHash('sha256').update(lockBuf).digest('hex').slice(0, 16);
    if (stamped !== actual) problems.push({ localRef, localSha, stamped, actual });
}

if (problems.length === 0) process.exit(0);

process.stderr.write(`\nPush stopped: ${NOTICES} does not match ${LOCK}.\n\n`);
for (const p of problems) {
    let subject = p.localSha.slice(0, 9);
    try {
        subject = git(['log', '-1', '--format=%h %s', p.localSha]).trim();
    } catch {
        /* keep the bare sha */
    }
    process.stderr.write(
        `  ${p.localRef} -> ${subject}\n` +
            `      notices header records  ${p.stamped}\n` +
            `      lockfile at that commit ${p.actual}\n\n`
    );
}
process.stderr.write(
    `${NOTICES} is the licence attribution shipped with the product, so it has to\n` +
        `follow the production dependency tree. Regenerate it and commit the result:\n\n` +
        `  cd frontend && node scripts/generate-third-party-notices.mjs\n` +
        `  git add ${NOTICES} && git commit\n\n` +
        `Only the tip is checked, so one follow-up commit is enough — earlier commits\n` +
        `in the branch do not need rewriting.\n\n`
);

process.exit(1);
