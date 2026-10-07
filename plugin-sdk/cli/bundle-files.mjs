// @ts-check
import { lstatSync, readdirSync } from 'node:fs';
import path from 'node:path';

import { IGNORED_NAMES, UI_FOLDER } from './rules.mjs';

/**
 * @typedef {{ level: 'error' | 'warning', loc: string, message: string }} Problem
 * @typedef {{ path: string, source: string, size: number }} BundleFile
 *   `path`: the zip path (POSIX, relative to the zip root); `source`: the absolute file on disk.
 */

/**
 * Lists the files a plugin bundle is made of: everything under `dir` at the zip root, plus the UI
 * build (`uiDir`) under `ui/`. OS junk is skipped silently; other hidden files and symlinks are
 * skipped with a warning. Paths in `exclude` (absolute) are never listed.
 *
 * @param {string} dir
 * @param {string | null} uiDir
 * @param {readonly string[]} [exclude]
 * @returns {{ files: Map<string, BundleFile>, problems: Problem[] }}
 */
export function collectBundleFiles(dir, uiDir, exclude = []) {
    /** @type {Map<string, BundleFile>} */
    const files = new Map();
    /** @type {Problem[]} */
    const problems = [];
    const excluded = new Set(exclude.map((item) => path.resolve(item)));

    walk(path.resolve(dir), '', files, problems, excluded);
    if (uiDir !== null) {
        /** @type {Map<string, BundleFile>} */
        const uiFiles = new Map();
        walk(path.resolve(uiDir), UI_FOLDER, uiFiles, problems, excluded);
        for (const [zipPath, file] of uiFiles) {
            if (files.has(zipPath)) {
                problems.push({
                    level: 'error',
                    loc: zipPath,
                    message: `is both in the plugin folder and in the --ui build; keep one.`,
                });
                continue;
            }
            files.set(zipPath, file);
        }
    }
    return { files: new Map([...files].sort(([left], [right]) => compareZipPaths(left, right))), problems };
}

/**
 * Byte-order comparison of zip paths, so the order never depends on the locale.
 * @param {string} left
 * @param {string} right
 */
export function compareZipPaths(left, right) {
    return Buffer.compare(Buffer.from(left, 'utf8'), Buffer.from(right, 'utf8'));
}

/**
 * @param {string} folder
 * @param {string} prefix
 * @param {Map<string, BundleFile>} files
 * @param {Problem[]} problems
 * @param {ReadonlySet<string>} excluded
 */
function walk(folder, prefix, files, problems, excluded) {
    const entries = readdirSync(folder, { withFileTypes: true }).sort((left, right) =>
        compareZipPaths(left.name, right.name)
    );
    for (const entry of entries) {
        const source = path.join(folder, entry.name);
        const zipPath = prefix + entry.name;
        if (IGNORED_NAMES.includes(entry.name) || excluded.has(source)) continue;
        if (entry.name.startsWith('.')) {
            problems.push({ level: 'warning', loc: zipPath, message: 'is a hidden file and is not packed.' });
            continue;
        }
        if (entry.isSymbolicLink()) {
            problems.push({ level: 'warning', loc: zipPath, message: 'is a symbolic link and is not packed.' });
            continue;
        }
        if (entry.isDirectory()) {
            walk(source, `${zipPath}/`, files, problems, excluded);
        } else if (entry.isFile()) {
            files.set(zipPath, { path: zipPath, source, size: lstatSync(source).size });
        }
    }
}
