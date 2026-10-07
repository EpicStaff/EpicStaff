import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, test } from 'node:test';

import { lintHtml } from '../cli/html-lint.mjs';
import { validatePlugin } from '../cli/validate.mjs';
import { createPluginFixture, type PluginFixture, validManifest, validResources } from './helpers/plugin-fixture.ts';

const CLI = fileURLToPath(new URL('../bin/epicstaff-plugin.mjs', import.meta.url));

const fixtures: PluginFixture[] = [];
afterEach(() => {
    while (fixtures.length > 0) fixtures.pop()?.cleanup();
});

function fixture(): PluginFixture {
    const created = createPluginFixture();
    fixtures.push(created);
    return created;
}

function errorsOf(target: PluginFixture): Array<[string, string]> {
    const result = validatePlugin({ dir: target.pluginDir, uiDir: target.uiDir });
    return result.problems
        .filter((problem) => problem.level === 'error')
        .map((problem) => [problem.loc, problem.message]);
}

function assertError(target: PluginFixture, loc: string, fragment: string): void {
    const errors = errorsOf(target);
    assert.ok(
        errors.some(([errorLoc, message]) => errorLoc === loc && message.includes(fragment)),
        `expected an error at ${loc} containing "${fragment}", got ${JSON.stringify(errors, null, 2)}`
    );
}

type Json = Record<string, unknown>;
type JsonList = Json[];

describe('validate', () => {
    test('accepts a valid bridge-2 plugin with a UI build', () => {
        const target = fixture();
        const result = validatePlugin({ dir: target.pluginDir, uiDir: target.uiDir });
        assert.deepEqual(result.problems, []);
        assert.deepEqual(
            [...result.files.keys()],
            [
                'plugin.json',
                'resources.json',
                'ui/chunk-DEF.js',
                'ui/icon.svg',
                'ui/index.html',
                'ui/main-ABC.js',
                'ui/media/inter-latin-400-normal.woff2',
                'ui/styles-ABC.css',
            ]
        );
    });

    test('rejects key_value_table access with bridge 1', () => {
        const target = fixture();
        target.writeManifest({ ...validManifest(), bridge: 1 });
        assertError(target, 'plugin.json.access.1.type', 'needs "bridge": 2');
    });

    test('rejects an action that is not valid for the access type', () => {
        const target = fixture();
        const manifest = validManifest();
        (manifest['access'] as JsonList)[1] = {
            alias: 'conversations',
            type: 'key_value_table',
            ref: 1,
            actions: ['run'],
        };
        (manifest['access'] as JsonList)[0] = { alias: 'chat', type: 'flow', ref: 1, actions: ['read'] };
        target.writeManifest(manifest);
        assertError(target, 'plugin.json.access.1.actions.0', "'run' is not an action of key_value_table");
        assertError(target, 'plugin.json.access.0.actions.0', "'read' is not an action of flow");
    });

    test('rejects an access ref that is not a KeyValueTable in resources.json', () => {
        const target = fixture();
        const manifest = validManifest();
        (manifest['access'] as JsonList)[1] = {
            alias: 'conversations',
            type: 'key_value_table',
            ref: 9,
            actions: ['read'],
        };
        target.writeManifest(manifest);
        assertError(target, 'plugin.json.access.1.ref', 'resources.json has no KeyValueTable with id 9');
    });

    test('rejects a key-value node using a table the plugin does not ship', () => {
        const target = fixture();
        const resources = validResources();
        const nodes = ((resources['Flow'] as JsonList)[0] as Json)['nodes'] as JsonList;
        nodes.push({
            id: 5,
            node_type: 'KeyValueNode',
            node_name: 'Read customers',
            key_value_table: 77,
            key_value_table_name: 'customers',
        });
        nodes.push({
            id: 6,
            node_type: 'KeyValueNode',
            node_name: 'By name only',
            key_value_table: null,
            key_value_table_name: 'customers',
        });
        nodes.push({
            id: 7,
            node_type: 'KeyValueNode',
            node_name: 'Unbound',
            key_value_table: null,
            key_value_table_name: null,
        });
        target.writeResources(resources);
        const errors = errorsOf(target).filter(([, message]) => message.includes('does not ship'));
        assert.deepEqual(
            errors.map(([loc]) => loc),
            ['resources.json.Flow.1.Read customers', 'resources.json.Flow.1.By name only']
        );
    });

    test('rejects a table whose installed name is longer than 255 characters', () => {
        const target = fixture();
        const resources = validResources();
        resources['KeyValueTable'] = [{ id: 1, name: 'n'.repeat(250) }];
        target.writeResources(resources);
        assertError(target, 'resources.json.KeyValueTable.1.name', 'is longer than 255 characters');
    });

    test('rejects a table without a real name and names that differ only in case', () => {
        const target = fixture();
        const resources = validResources();
        resources['KeyValueTable'] = [
            { id: 1, name: 'conversations' },
            { id: 2, name: '   ' },
            { id: 3, name: 'Conversations' },
        ];
        target.writeResources(resources);
        assertError(target, 'resources.json.KeyValueTable.2.name', 'needs a name');
        assertError(target, 'resources.json.KeyValueTable.3.name', "Two key-value tables are named 'Conversations'");
    });

    test('rejects a resources.json version EpicStaff cannot read', () => {
        const target = fixture();
        for (const [version, fragment] of [
            [4, 'File version 4 is newer than supported 3'],
            ['3', 'must be an integer'],
            [0, 'No migration path from version 0'],
        ] as const) {
            target.writeResources({ ...validResources(), version });
            assertError(target, 'resources.json.version', fragment);
        }
        const { version: _omitted, ...withoutVersion } = validResources();
        target.writeResources(withoutVersion);
        assert.deepEqual(errorsOf(target), [], 'an absent version means 1, which EpicStaff converts');
    });

    test('rejects unknown fields, a secret slot carrying a value, and bad identity fields', () => {
        const target = fixture();
        target.writeManifest({
            ...validManifest(),
            id: 'Chat_Admin',
            version: 'one',
            homepage: 'https://example.com',
            secret_slots: [{ name: 'OPENAI_API_KEY', value: 'sk-123' }],
        });
        assertError(target, 'plugin.json.homepage', 'not a known field');
        assertError(target, 'plugin.json.secret_slots.0.value', 'not a known field');
        assertError(target, 'plugin.json.id', 'lowercase id');
        assertError(target, 'plugin.json.version', 'version such as 0.1.0');
    });

    test('rejects disallowed UI types, a missing entry and resource types a plugin may not carry', () => {
        const target = fixture();
        target.write('browser/server.php', '<?php');
        target.write('browser/run.sh', 'echo');
        target.writeManifest({ ...validManifest(), ui: { entry: 'ui/app.html' } });
        target.writeResources({ ...validResources(), Session: [{ id: 1 }] });
        assertError(target, 'ui/server.php', 'UI files must be one of');
        assertError(target, 'ui/run.sh', 'blocked executable extension');
        assertError(target, 'plugin.json.ui.entry', "no 'ui/app.html'");
        assertError(target, 'resources.json.Session', 'cannot contain Session');
    });

    test('rejects more than 300 UI files', () => {
        const target = fixture();
        for (let index = 0; index < 300; index++) target.write(`browser/chunk-${index}.js`, '');
        assertError(target, 'ui/', 'the limit is 300');
    });

    test('rejects HTML the sandbox would break', () => {
        const target = fixture();
        target.write(
            'browser/index.html',
            '<html><head><base href="/"><script>window.x = 1</script></head>' +
                '<body onload="start()"><a href="javascript:void(0)">x</a>' +
                '<script src="https://cdn.example.com/lib.js"></script></body></html>'
        );
        assertError(target, 'ui/index.html', 'inline <script>');
        assertError(target, 'ui/index.html', 'inline event handler (onload=)');
        assertError(target, 'ui/index.html', 'javascript: URL');
        const warnings = validatePlugin({ dir: target.pluginDir, uiDir: target.uiDir })
            .problems.filter((problem) => problem.level === 'warning')
            .map((problem) => problem.message);
        assert.ok(warnings.some((message) => message.includes('<base>')));
        assert.ok(warnings.some((message) => message.includes('https://cdn.example.com/lib.js')));
    });

    test('rejects Python code that reads a secret by name, ignoring comments', () => {
        const target = fixture();
        const resources = validResources();
        const nodes = ((resources['Flow'] as JsonList)[0] as Json)['nodes'] as JsonList;
        nodes.push({
            id: 8,
            node_type: 'PythonNode',
            node_name: 'Leaky',
            python_code: { code: 'key = get_secret("OPENAI_API_KEY")' },
        });
        target.writeResources(resources);
        const errors = errorsOf(target).filter(([, message]) => message.includes('reads secrets by name'));
        assert.deepEqual(
            errors.map(([loc, message]) => [loc, message.includes('IN_A_COMMENT')]),
            [['resources.json.Flow.1.Leaky', false]]
        );
    });

    test('reports a file that is both in the plugin folder and in the UI build', () => {
        const target = fixture();
        target.write('plugin/ui/icon.svg', '<svg/>');
        assertError(target, 'ui/icon.svg', 'both in the plugin folder and in the --ui build');
    });
});

describe('lintHtml', () => {
    test('passes an Angular production index.html', () => {
        const html =
            '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>App</title>' +
            '<link rel="modulepreload" href="chunk-A.js"><link rel="stylesheet" href="styles-B.css"></head>' +
            '<body><app-root></app-root><script src="main-C.js" type="module"></script></body></html>';
        assert.deepEqual(lintHtml(html, 'ui/index.html'), []);
    });

    test('ignores commented-out markup and anchors to outside pages', () => {
        const html = '<!-- <script>alert(1)</script> --><a href="https://epicstaff.ai">site</a>';
        assert.deepEqual(lintHtml(html, 'ui/index.html'), []);
    });
});

describe('epicstaff-plugin validate (CLI)', () => {
    test('exits 0 for a valid plugin, 1 with readable errors for an invalid one, 2 on bad usage', () => {
        const target = fixture();
        const ok = spawnSync(process.execPath, [CLI, 'validate', target.pluginDir, '--ui', target.uiDir], {
            encoding: 'utf8',
        });
        assert.equal(ok.status, 0, ok.stderr);
        assert.match(ok.stdout, /The plugin is valid: 8 files, 0 errors, 0 warnings\./);

        target.writeManifest({ ...validManifest(), bridge: 1 });
        const bad = spawnSync(process.execPath, [CLI, 'validate', target.pluginDir, `--ui=${target.uiDir}`], {
            encoding: 'utf8',
        });
        assert.equal(bad.status, 1);
        assert.match(
            bad.stderr,
            /^error +plugin\.json\.access\.1\.type +key_value_table access needs "bridge": 2 or newer\.$/m
        );
        assert.match(bad.stderr, /The plugin is not valid: 1 error, 0 warnings\./);

        const usage = spawnSync(process.execPath, [CLI, 'validate', target.pluginDir, '--uix', 'x'], {
            encoding: 'utf8',
        });
        assert.equal(usage.status, 2);
        assert.match(usage.stderr, /Unknown option --uix/);
    });
});
