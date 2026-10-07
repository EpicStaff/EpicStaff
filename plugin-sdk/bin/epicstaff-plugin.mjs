#!/usr/bin/env node
// @ts-check
/**
 * epicstaff-plugin — checks and packs EpicStaff plugins.
 *
 *   epicstaff-plugin validate <plugin-dir> [--ui <ui-build-dir>]
 *   epicstaff-plugin pack <plugin-dir> [--ui <ui-build-dir>] --out <plugin.zip>
 *
 * Exit codes: 0 valid / packed, 1 the plugin has errors, 2 wrong usage.
 */
import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { packPlugin } from '../cli/pack.mjs';
import { formatBytes, validatePlugin } from '../cli/validate.mjs';

/** @typedef {import('../cli/bundle-files.mjs').Problem} Problem */

const USAGE = `Usage:
  epicstaff-plugin validate <plugin-dir> [--ui <ui-build-dir>]
  epicstaff-plugin pack <plugin-dir> [--ui <ui-build-dir>] --out <plugin.zip>

  <plugin-dir>     folder with plugin.json, resources.json and optional knowledge/, files/, ui/
  --ui <dir>       a built app (e.g. dist/<app>/browser) to place under ui/ in the zip
  --out <file>     where pack writes the zip

Options: --help, --version`;

class UsageError extends Error {}

/**
 * @param {string[]} argv
 * @returns {{ command: string, dir: string, uiDir: string | null, out: string | null }}
 */
function parseArguments(argv) {
    /** @type {string[]} */
    const positional = [];
    /** @type {Record<string, string>} */
    const options = {};
    for (let index = 0; index < argv.length; index++) {
        const argument = argv[index] ?? '';
        if (!argument.startsWith('--')) {
            positional.push(argument);
            continue;
        }
        const [name = '', inlineValue] = argument.slice(2).split(/=(.*)/s, 2);
        if (name !== 'ui' && name !== 'out') throw new UsageError(`Unknown option --${name}.`);
        const value = inlineValue ?? argv[++index];
        if (value === undefined || value === '' || value.startsWith('--'))
            throw new UsageError(`--${name} needs a value.`);
        options[name] = value;
    }
    const [command, dir, ...extra] = positional;
    if (command !== 'validate' && command !== 'pack')
        throw new UsageError(command ? `Unknown command "${command}".` : 'Name a command.');
    if (!dir) throw new UsageError('Name the plugin folder.');
    if (extra.length > 0) throw new UsageError(`Unexpected argument "${extra[0]}".`);
    if (command === 'pack' && !options['out']) throw new UsageError('pack needs --out <plugin.zip>.');
    if (command === 'validate' && options['out']) throw new UsageError('--out is only for pack.');
    requireFolder(dir, 'The plugin folder');
    if (options['ui']) requireFolder(options['ui'], 'The --ui folder');
    return { command, dir, uiDir: options['ui'] ?? null, out: options['out'] ?? null };
}

/**
 * @param {string} folder
 * @param {string} what
 */
function requireFolder(folder, what) {
    if (!existsSync(folder) || !statSync(folder).isDirectory())
        throw new UsageError(`${what} ${folder} does not exist or is not a folder.`);
}

/** @param {readonly Problem[]} problems */
function printProblems(problems) {
    const ordered = [
        ...problems.filter((problem) => problem.level === 'error'),
        ...problems.filter((problem) => problem.level === 'warning'),
    ];
    for (const problem of ordered) {
        const label = problem.level === 'error' ? 'error  ' : 'warning';
        process.stderr.write(`${label}  ${problem.loc}  ${problem.message}\n`);
    }
}

/**
 * @param {number} errors
 * @param {number} warnings
 */
function summary(errors, warnings) {
    const plural = (/** @type {number} */ count, /** @type {string} */ word) =>
        `${count} ${word}${count === 1 ? '' : 's'}`;
    return `${plural(errors, 'error')}, ${plural(warnings, 'warning')}`;
}

function packageVersion() {
    const file = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'package.json');
    return String(JSON.parse(readFileSync(file, 'utf8')).version);
}

function main() {
    const argv = process.argv.slice(2);
    if (argv.length === 0 || argv.includes('--help') || argv.includes('-h')) {
        process.stdout.write(`${USAGE}\n`);
        return argv.length === 0 ? 2 : 0;
    }
    if (argv.includes('--version')) {
        process.stdout.write(`${packageVersion()}\n`);
        return 0;
    }

    let parsed;
    try {
        parsed = parseArguments(argv);
    } catch (error) {
        if (!(error instanceof UsageError)) throw error;
        process.stderr.write(`${error.message}\n\n${USAGE}\n`);
        return 2;
    }

    if (parsed.command === 'validate') {
        const result = validatePlugin({ dir: parsed.dir, uiDir: parsed.uiDir });
        printProblems(result.problems);
        if (result.errorCount > 0) {
            process.stderr.write(`\nThe plugin is not valid: ${summary(result.errorCount, result.warningCount)}.\n`);
            return 1;
        }
        process.stdout.write(`The plugin is valid: ${result.files.size} files, ${summary(0, result.warningCount)}.\n`);
        return 0;
    }

    const result = packPlugin({ dir: parsed.dir, uiDir: parsed.uiDir, out: parsed.out ?? '' });
    printProblems(result.problems);
    if (result.output === null) {
        process.stderr.write(`\nNothing was written: ${summary(result.errorCount, result.warningCount)}.\n`);
        return 1;
    }
    process.stdout.write(
        `Packed ${result.fileCount} files (${formatBytes(result.unpackedBytes)} → ${formatBytes(result.zipBytes)}) into ${result.output}` +
            ` — ${summary(0, result.warningCount)}.\n`
    );
    return 0;
}

process.exitCode = main();
