import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

export const ICON_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4 4h16v12H7l-3 3z"/></svg>';

export const INDEX_HTML = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Chat Admin</title>
    <link rel="stylesheet" href="styles-ABC.css" />
    <script type="application/json" id="config">{"data": "blocks are fine"}</script>
  </head>
  <body>
    <app-root></app-root>
    <script src="main-ABC.js" type="module"></script>
  </body>
</html>
`;

/** A valid bridge-2 manifest: a flow and a key-value table, both in resources.json. */
export function validManifest(): Record<string, unknown> {
    return {
        format_version: 1,
        bridge: 2,
        id: 'chat-admin',
        version: '0.1.0',
        name: 'Chat Admin',
        description: 'Chat with the assistant and browse past conversations.',
        icon: 'ui/icon.svg',
        ui: { entry: 'ui/index.html' },
        secret_slots: [{ name: 'OPENAI_API_KEY', description: 'Key for the chat model.' }],
        secret_bindings: [{ entity: 'LLMConfig', ref: 1, field: 'api_key_secret', slot: 'OPENAI_API_KEY' }],
        access: [
            { alias: 'chat', type: 'flow', ref: 1, actions: ['run', 'sessions.read', 'sessions.stop'] },
            { alias: 'conversations', type: 'key_value_table', ref: 1, actions: ['read'] },
        ],
    };
}

export function validResources(): Record<string, unknown> {
    return {
        main_entity: 'Flow',
        version: 3,
        Flow: [
            {
                id: 1,
                name: 'Chat Admin',
                nodes: [
                    { id: 1, node_type: 'StartNode', variables: { conversation_id: '', question: '' } },
                    {
                        id: 2,
                        node_type: 'KeyValueNode',
                        node_name: 'Load conversation',
                        mode: 'read',
                        key_value_table: 1,
                        key_value_table_name: 'conversations',
                    },
                    {
                        id: 3,
                        node_type: 'PythonNode',
                        node_name: 'Append turn',
                        python_code: { code: 'def main(record):\n    # get_secret("IN_A_COMMENT")\n    return record' },
                    },
                    { id: 4, node_type: 'EndNode', output_map: {} },
                ],
                conditional_edge_list: [],
            },
        ],
        KeyValueTable: [{ id: 1, name: 'conversations', description: 'One entry per conversation.' }],
        LLMConfig: [{ id: 1, custom_name: 'Chat model' }],
        LLMModel: [{ id: 1, name: 'gpt-4o-mini' }],
    };
}

export interface PluginFixture {
    root: string;
    pluginDir: string;
    uiDir: string;
    write(relativePath: string, content: string | Uint8Array): void;
    writeManifest(manifest: Record<string, unknown>): void;
    writeResources(resources: Record<string, unknown>): void;
    cleanup(): void;
}

/** A temp folder holding `plugin/` (plugin.json + resources.json) and `browser/` (a UI build). */
export function createPluginFixture(): PluginFixture {
    const root = mkdtempSync(path.join(tmpdir(), 'epicstaff-plugin-'));
    const pluginDir = path.join(root, 'plugin');
    const uiDir = path.join(root, 'browser');
    const fixture: PluginFixture = {
        root,
        pluginDir,
        uiDir,
        write(relativePath, content) {
            const target = path.join(root, relativePath);
            mkdirSync(path.dirname(target), { recursive: true });
            writeFileSync(target, content);
        },
        writeManifest(manifest) {
            fixture.write('plugin/plugin.json', JSON.stringify(manifest, null, 2));
        },
        writeResources(resources) {
            fixture.write('plugin/resources.json', JSON.stringify(resources, null, 2));
        },
        cleanup() {
            rmSync(root, { recursive: true, force: true });
        },
    };
    fixture.writeManifest(validManifest());
    fixture.writeResources(validResources());
    fixture.write('browser/index.html', INDEX_HTML);
    fixture.write('browser/main-ABC.js', 'import("./chunk-DEF.js");\n'.repeat(40));
    fixture.write('browser/chunk-DEF.js', 'export const x = 1;\n');
    fixture.write('browser/styles-ABC.css', 'body { font-family: Inter; }\n'.repeat(50));
    fixture.write('browser/media/inter-latin-400-normal.woff2', new Uint8Array([0x77, 0x4f, 0x46, 0x32, 1, 2, 3]));
    fixture.write('browser/icon.svg', ICON_SVG);
    return fixture;
}
