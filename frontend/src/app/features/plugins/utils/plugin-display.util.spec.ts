import { HttpErrorResponse } from '@angular/common/http';

import {
    describePluginAccess,
    describeSecretDestination,
    groupPluginContents,
    isPluginIconUrl,
    pluginStatusLabel,
    resourceTypeLabel,
} from './plugin-display.util';
import { toPluginErrorView } from './plugin-error.util';

describe('plugin display helpers', () => {
    it('describes an access entry in plain words', () => {
        expect(describePluginAccess({ resource_name: 'Chat Bot', actions: ['run', 'sessions.read'] })).toBe(
            "Run flow 'Chat Bot' and read its sessions"
        );
        expect(
            describePluginAccess({ resource_name: 'Chat Bot', actions: ['run', 'sessions.read', 'sessions.stop'] })
        ).toBe("Run flow 'Chat Bot', read its sessions and stop its sessions");
        expect(describePluginAccess({ resource_name: 'Chat Bot', actions: ['sessions.read'] })).toBe(
            "Read the sessions of flow 'Chat Bot'"
        );
    });

    it('describes read access to a key-value table, and one that no longer exists', () => {
        expect(
            describePluginAccess({
                type: 'key_value_table',
                resource_name: 'chat_admin__conversations',
                actions: ['read'],
            })
        ).toBe("Read key-value table 'chat_admin__conversations'");
        expect(describePluginAccess({ type: 'key_value_table', resource_name: null, actions: ['read'] })).toBe(
            'Read a key-value table that no longer exists'
        );
        expect(describePluginAccess({ type: 'flow', resource_name: 'Chat', actions: ['run'] })).toBe("Run flow 'Chat'");
    });

    it('labels key-value tables and the model types a plugin can create', () => {
        expect(resourceTypeLabel('key_value_table', 1)).toBe('Key-value table');
        expect(resourceTypeLabel('key_value_table', 2)).toBe('Key-value tables');
        expect(resourceTypeLabel('llm_model', 1)).toBe('LLM model');
        expect(resourceTypeLabel('embedding_model', 2)).toBe('Embedding models');
    });

    it('labels each status, with the reason when it needs attention', () => {
        expect(pluginStatusLabel({ status: 'preparing', status_reason: '' })).toBe('Preparing knowledge…');
        expect(pluginStatusLabel({ status: 'ready', status_reason: '' })).toBe('Ready');
        expect(pluginStatusLabel({ status: 'needs_attention', status_reason: 'Indexing failed' })).toBe(
            'Needs attention: Indexing failed'
        );
        expect(pluginStatusLabel({ status: 'suspended', status_reason: '' })).toBe('Suspended');
    });

    it('says where a secret is sent, and flags any explicit host as custom', () => {
        expect(
            describeSecretDestination({ resource_type: 'llm_config', name: 'Chat', provider: 'openai', host: null })
        ).toEqual({
            target: "Sent to: openai's standard endpoint",
            via: "by LLM configuration 'Chat'",
            isCustomHost: false,
        });
        expect(
            describeSecretDestination({
                resource_type: 'mcp_tool',
                name: 'Search',
                provider: null,
                host: 'mcp.example.com',
            })
        ).toEqual({
            target: 'Sent to: mcp.example.com (custom endpoint)',
            via: "by MCP tool 'Search'",
            isCustomHost: true,
        });
        expect(
            describeSecretDestination({ resource_type: 'embedding_config', name: 'Docs', provider: null, host: null })
                .target
        ).toBe("Sent to: its provider's standard endpoint");
    });

    it('accepts only PNG and SVG data URLs as icons', () => {
        expect(isPluginIconUrl('data:image/svg+xml;base64,PHN2Zz4=')).toBe(true);
        expect(isPluginIconUrl('data:image/png;base64,iVBORw0KGgo=')).toBe(true);
        expect(isPluginIconUrl('javascript:alert(1)')).toBe(false);
        expect(isPluginIconUrl('https://example.com/icon.svg')).toBe(false);
        expect(isPluginIconUrl('')).toBe(false);
    });

    it('groups contents by type in display order', () => {
        const groups = groupPluginContents([
            { type: 'secret', ref: 'KEY', name: 'CHAT_BOT__KEY' },
            { type: 'key_value_table', ref: '1', name: 'chat_admin__conversations' },
            { type: 'flow', ref: '1', name: 'Chat Bot' },
            { type: 'source_collection', ref: 'Docs', name: 'Docs', documents: ['a.md', 'b.md'] },
        ]);

        expect(groups.map((group) => group.label)).toEqual([
            'Flow',
            'Key-value table',
            'Knowledge collection',
            'Secret',
        ]);
        expect(groups[2].items[0].detail).toBe('2 documents: a.md, b.md');
    });

    it('turns the 409 already-installed envelope into a clear message', () => {
        const error = new HttpErrorResponse({
            status: 409,
            error: {
                status_code: 409,
                code: 'plugin_already_installed',
                message: 'A plugin with this id is already installed.',
                errors: [{ plugin_id: 'chat-bot', installed_version: '0.1.0' }],
            },
        });

        const view = toPluginErrorView(error, 'fallback');

        expect(view.code).toBe('plugin_already_installed');
        expect(view.message).toBe('This plugin is already installed (version 0.1.0).');
    });

    it('lists every invalid_plugin problem with its location', () => {
        const error = new HttpErrorResponse({
            status: 400,
            error: {
                status_code: 400,
                code: 'invalid_plugin',
                message: 'The plugin file is invalid: 1 problem found.',
                errors: [{ loc: 'plugin.json.secret_slots.0.value', message: 'Extra inputs are not permitted' }],
            },
        });

        expect(toPluginErrorView(error, 'fallback').details).toEqual([
            'plugin.json.secret_slots.0.value: Extra inputs are not permitted',
        ]);
    });
});
