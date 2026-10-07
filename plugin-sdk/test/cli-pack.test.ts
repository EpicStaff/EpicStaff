import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, symlinkSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, test } from 'node:test';

import { packPlugin } from '../cli/pack.mjs';
import { crc32, createZip, memberNameProblem } from '../cli/zip.mjs';
import { createPluginFixture, INDEX_HTML, type PluginFixture, validManifest } from './helpers/plugin-fixture.ts';

const CLI = fileURLToPath(new URL('../bin/epicstaff-plugin.mjs', import.meta.url));

/** Reads a zip with Python's zipfile, the reader EpicStaff's server uses. */
const PYTHON_READER = `
import json, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    print(json.dumps({
        "names": archive.namelist(),
        "bad": archive.testzip(),
        "methods": {info.filename: info.compress_type for info in archive.infolist()},
        "dirs": [info.filename for info in archive.infolist() if info.is_dir()],
        "index_html": archive.read("ui/index.html").decode("utf-8"),
        "font": list(archive.read("ui/media/inter-latin-400-normal.woff2")),
    }))
`;

const fixtures: PluginFixture[] = [];
afterEach(() => {
    while (fixtures.length > 0) fixtures.pop()?.cleanup();
});

function fixture(): PluginFixture {
    const created = createPluginFixture();
    fixtures.push(created);
    return created;
}

function hasPython(): boolean {
    return spawnSync('python3', ['--version']).status === 0;
}

describe('pack', () => {
    test('writes a zip Python zipfile reads: sorted files, no directory entries, ui/ from the build', (context) => {
        if (!hasPython()) {
            context.skip('python3 is not installed');
            return;
        }
        const target = fixture();
        const out = path.join(target.root, 'out', 'chat-admin-plugin.zip');

        const result = packPlugin({ dir: target.pluginDir, uiDir: target.uiDir, out });

        assert.equal(result.errorCount, 0, JSON.stringify(result.problems));
        assert.equal(result.output, out);
        const read = spawnSync('python3', ['-I', '-c', PYTHON_READER, out], { encoding: 'utf8' });
        assert.equal(read.status, 0, read.stderr);
        const archive = JSON.parse(read.stdout) as {
            names: string[];
            bad: string | null;
            methods: Record<string, number>;
            dirs: string[];
            index_html: string;
            font: number[];
        };
        assert.deepEqual(archive.names, [
            'plugin.json',
            'resources.json',
            'ui/chunk-DEF.js',
            'ui/icon.svg',
            'ui/index.html',
            'ui/main-ABC.js',
            'ui/media/inter-latin-400-normal.woff2',
            'ui/styles-ABC.css',
        ]);
        assert.equal(archive.bad, null, 'every CRC checks out');
        assert.deepEqual(archive.dirs, []);
        assert.equal(archive.index_html, INDEX_HTML);
        assert.deepEqual(archive.font, [0x77, 0x4f, 0x46, 0x32, 1, 2, 3]);
        assert.equal(archive.methods['ui/main-ABC.js'], 8, 'repetitive text is deflated');
        assert.equal(archive.methods['ui/media/inter-latin-400-normal.woff2'], 0, 'tiny binary is stored');
    });

    test('is deterministic: the same input gives the same bytes', () => {
        const target = fixture();
        const first = path.join(target.root, 'first.zip');
        const second = path.join(target.root, 'second.zip');
        packPlugin({ dir: target.pluginDir, uiDir: target.uiDir, out: first });
        packPlugin({ dir: target.pluginDir, uiDir: target.uiDir, out: second });
        assert.ok(readFileSync(first).equals(readFileSync(second)));
    });

    test('writes nothing when the plugin is invalid', () => {
        const target = fixture();
        target.writeManifest({ ...validManifest(), bridge: 1 });
        const out = path.join(target.root, 'invalid.zip');

        const result = packPlugin({ dir: target.pluginDir, uiDir: target.uiDir, out });

        assert.equal(result.output, null);
        assert.ok(result.errorCount > 0);
        assert.equal(existsSync(out), false);
    });

    test('refuses an output that reaches the plugin folder through a symlink', () => {
        const target = fixture();
        const link = path.join(target.root, 'link-to-plugin');
        symlinkSync(target.pluginDir, link, 'dir');
        const result = packPlugin({ dir: target.pluginDir, uiDir: target.uiDir, out: path.join(link, 'self.zip') });
        assert.equal(result.output, null);
        assert.ok(
            result.problems.some((problem) => problem.loc === '--out' && problem.message.includes('pack itself'))
        );
    });

    test('explains an --out that is an existing folder', () => {
        const target = fixture();
        const folder = path.join(target.root, 'out-folder');
        mkdirSync(folder);
        const result = packPlugin({ dir: target.pluginDir, uiDir: target.uiDir, out: folder });
        assert.equal(result.output, null);
        assert.ok(
            result.problems.some((problem) => problem.loc === '--out' && problem.message.includes('is a folder'))
        );
    });

    test('refuses an output inside the plugin folder', () => {
        const target = fixture();
        const result = packPlugin({
            dir: target.pluginDir,
            uiDir: target.uiDir,
            out: path.join(target.pluginDir, 'self.zip'),
        });
        assert.equal(result.output, null);
        assert.ok(result.problems.some((problem) => problem.loc === '--out'));
    });

    test('the CLI packs and prints a summary', () => {
        const target = fixture();
        const out = path.join(target.root, 'cli.zip');
        const run = spawnSync(process.execPath, [CLI, 'pack', target.pluginDir, '--ui', target.uiDir, '--out', out], {
            encoding: 'utf8',
        });
        assert.equal(run.status, 0, run.stderr);
        assert.match(run.stdout, /^Packed 8 files \(.+\) into .+cli\.zip — 0 errors, 0 warnings\.\n$/);

        const missingOut = spawnSync(process.execPath, [CLI, 'pack', target.pluginDir], { encoding: 'utf8' });
        assert.equal(missingOut.status, 2);
        assert.match(missingOut.stderr, /pack needs --out/);
    });
});

describe('zip member names', () => {
    test('only relative POSIX file paths without dot segments are written', () => {
        assert.equal(memberNameProblem('ui/main.js'), null);
        assert.equal(memberNameProblem('ui/.well-known.json'), null, 'a dot at the start of a name is fine');
        for (const name of [
            '../evil.js',
            'ui/../../evil.js',
            'ui/./a.js',
            'ui//a.js',
            '/abs.js',
            'ui\\a.js',
            'C:evil.js',
            'ui/',
            '',
        ]) {
            assert.notEqual(memberNameProblem(name), null, name);
        }
        assert.throws(() => createZip([{ name: 'ui/../x.js', data: new Uint8Array([1]) }]), /segment/);
    });
});

describe('crc32', () => {
    test('matches the IEEE check value', () => {
        assert.equal(crc32(new TextEncoder().encode('123456789')), 0xcbf43926);
    });
});
