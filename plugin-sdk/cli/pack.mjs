// @ts-check
import {
    existsSync,
    mkdirSync,
    readFileSync,
    realpathSync,
    renameSync,
    rmSync,
    statSync,
    writeFileSync,
} from 'node:fs';
import path from 'node:path';

import { LIMITS } from './rules.mjs';
import { formatBytes, validatePlugin } from './validate.mjs';
import { createZip } from './zip.mjs';

/**
 * @typedef {import('./bundle-files.mjs').Problem} Problem
 *
 * @typedef {object} PackResult
 * @property {Problem[]} problems
 * @property {number} errorCount
 * @property {number} warningCount
 * @property {string | null} output  the written zip, or `null` when nothing was written
 * @property {number} fileCount
 * @property {number} unpackedBytes
 * @property {number} zipBytes
 */

/**
 * Validates, then writes the plugin zip: the contents of `dir` at the zip root plus the UI build
 * under `ui/`, sorted by path, without directory entries. Nothing is written when validation
 * finds an error or the zip would exceed the size limit.
 *
 * @param {{ dir: string, uiDir?: string | null, out: string }} options
 * @returns {PackResult}
 */
export function packPlugin({ dir, uiDir = null, out }) {
    const output = path.resolve(out);
    const realOutput = realPath(output);
    /** @type {Problem[]} */
    const usageProblems = [];
    if (existsSync(output) && statSync(output).isDirectory()) {
        usageProblems.push({
            level: 'error',
            loc: '--out',
            message: `${out} is a folder; name the zip file to write, e.g. ${path.join(out, 'plugin.zip')}.`,
        });
    }
    for (const source of [dir, uiDir]) {
        // Real paths, so a symlinked folder or output can't hide that the zip would pack itself.
        if (source !== null && isInside(realOutput, realPath(path.resolve(source)))) {
            usageProblems.push({
                level: 'error',
                loc: '--out',
                message: `must not be inside ${source}; the zip would pack itself.`,
            });
        }
    }
    const validation = validatePlugin({ dir, uiDir, exclude: [output, realOutput] });
    const problems = [...usageProblems, ...validation.problems];
    let errorCount = usageProblems.length + validation.errorCount;
    const files = [...validation.files.values()];
    const unpackedBytes = files.reduce((total, file) => total + file.size, 0);
    const result = {
        problems,
        errorCount,
        warningCount: validation.warningCount,
        output: null,
        fileCount: files.length,
        unpackedBytes,
        zipBytes: 0,
    };
    if (errorCount > 0) return result;

    const zip = createZip(files.map((file) => ({ name: file.path, data: readFileSync(file.source) })));
    if (zip.length > LIMITS.zipBytes) {
        problems.push({
            level: 'error',
            loc: 'bundle',
            message: `The zip is ${formatBytes(zip.length)}; the limit is ${formatBytes(LIMITS.zipBytes)}.`,
        });
        errorCount++;
        return { ...result, errorCount, zipBytes: zip.length };
    }

    mkdirSync(path.dirname(output), { recursive: true });
    const temporary = `${output}.${process.pid}.tmp`;
    try {
        writeFileSync(temporary, zip);
        renameSync(temporary, output);
    } finally {
        rmSync(temporary, { force: true });
    }
    return { ...result, output, zipBytes: zip.length };
}

/**
 * @param {string} candidate
 * @param {string} folder
 */
function isInside(candidate, folder) {
    const relative = path.relative(folder, candidate);
    const leaves = relative === '..' || relative.startsWith(`..${path.sep}`);
    return relative !== '' && !leaves && !path.isAbsolute(relative);
}

/**
 * The real path of `target`; for a path that does not exist yet, the real path of its closest
 * existing ancestor plus the rest.
 * @param {string} target  an absolute path
 * @returns {string}
 */
function realPath(target) {
    try {
        return realpathSync(target);
    } catch {
        const parent = path.dirname(target);
        return parent === target ? target : path.join(realPath(parent), path.basename(target));
    }
}
