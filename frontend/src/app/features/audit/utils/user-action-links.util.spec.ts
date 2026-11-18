import { ActionCode, ResourceCode } from '@shared/models';

import { CanFunction } from '../../recycle-bin/models/recycle-bin.model';
import { AuditUserAction } from '../models/audit-user-action.models';
import { PageAccess, userActionParentUrl, userActionTargetUrl } from './user-action-links.util';

const baseAction: AuditUserAction = {
    id: 'action-1',
    org_id: 1,
    event_time: '2026-10-30T10:00:00Z',
    record_time: null,
    filter_matched: true,
    number: 1,
    actor_user_id: 3,
    actor_email: 'ann@example.com',
    actor_api_key_name: null,
    action: 'updated',
    target_type: null,
    target_id: null,
    target_name: null,
    previous_name: null,
    parent_type: null,
    parent_id: null,
    parent_name: null,
    route: null,
};

const allowAll: CanFunction = () => true;

// `can` answers for the active org, `canInAnyOrg` for any org the viewer belongs to
function pageAccess({
    can = allowAll,
    canInAnyOrg = allowAll,
    isChatEnabled = true,
}: { can?: CanFunction; canInAnyOrg?: CanFunction; isChatEnabled?: boolean } = {}): PageAccess {
    return {
        permissions: {
            can,
            canAny: (resource, actions) => actions.some((action) => can(resource, action)),
            canInAnyOrg,
        },
        isChatEnabled,
    };
}

const openEverything = pageAccess();
const denying =
    (deniedResource: ResourceCode): CanFunction =>
    (resource) =>
        resource !== deniedResource;

const inFlow = { parent_type: 'flow', parent_id: '4', parent_name: 'Billing' };
const inCollection = { parent_type: 'knowledge collection', parent_id: '6', parent_name: 'Manuals' };

describe('userActionTargetUrl', () => {
    it.each<[string, Partial<AuditUserAction>, string | null]>([
        ['a flow', { target_type: 'flow', target_id: '4' }, '/flows/4'],
        [
            'a python code node in its flow',
            { target_type: 'python code node', target_id: '12', ...inFlow },
            '/flows/4?nodeId=12',
        ],
        [
            'a subflow node in its flow',
            { target_type: 'subflow node', target_id: '13', ...inFlow },
            '/flows/4?nodeId=13',
        ],
        [
            'a key-value node in its flow',
            { target_type: 'key-value node', target_id: '14', ...inFlow },
            '/flows/4?nodeId=14',
        ],
        [
            'a knowledge retriever node in its flow',
            { target_type: 'knowledge retriever node', target_id: '15', ...inFlow },
            '/flows/4?nodeId=15',
        ],
        [
            'an audio to text node in its flow',
            { target_type: 'audio to text node', target_id: '16', ...inFlow },
            '/flows/4?nodeId=16',
        ],
        [
            'a classification decision table node in its flow',
            { target_type: 'classification decision table node', target_id: '17', ...inFlow },
            '/flows/4?nodeId=17',
        ],
        ['a session in its flow', { target_type: 'session', target_id: '88', ...inFlow }, '/graph/4/session/88'],
        ['a surface', { target_type: 'surface', target_id: '5' }, '/agents?surfaceId=5'],
        ['an agent', { target_type: 'agent', target_id: '7' }, '/agents?agentId=7'],
        [
            "an agent's voice settings, on its agent",
            { target_type: 'voice settings', target_id: '40', parent_type: 'agent', parent_id: '7' },
            '/agents?agentId=7',
        ],
        ['a custom tool', { target_type: 'custom tool', target_id: '3' }, '/tools/custom?toolId=3'],
        ['an MCP tool', { target_type: 'MCP tool', target_id: '3' }, '/tools/mcp?toolId=3'],
        [
            'a knowledge collection',
            { target_type: 'knowledge collection', target_id: '6' },
            '/storage/knowledge-sources?collection=6',
        ],
        [
            'a collection file, on its collection',
            { target_type: 'collection file', target_id: '50', ...inCollection },
            '/storage/knowledge-sources?collection=6',
        ],
        [
            'a naive RAG, on its collection with its configuration',
            { target_type: 'naive RAG', target_id: '11', ...inCollection },
            '/storage/knowledge-sources?collection=6&rag=11',
        ],
        [
            'a graph RAG, on its collection',
            { target_type: 'graph RAG', target_id: '12', ...inCollection },
            '/storage/knowledge-sources?collection=6',
        ],
        [
            'a key-value table',
            { target_type: 'key-value table', target_id: '8' },
            '/storage/key-value-tables?tableId=8',
        ],
        ['a venv', { target_type: 'venv', target_id: '9' }, '/venvs?venvId=9'],
        [
            'a webhook trigger',
            { target_type: 'webhook trigger', target_id: '21' },
            '/settings/webhook-triggers?triggerId=21',
        ],
        ['a voice channel', { target_type: 'voice channel', target_id: '22' }, '/settings/voice?channelId=22'],
        [
            "a channel's Twilio settings, on its channel",
            { target_type: 'Twilio settings', target_id: '60', parent_type: 'voice channel', parent_id: '22' },
            '/settings/voice?channelId=22',
        ],
        ['the default LLMs', { target_type: 'default LLMs', target_id: '1' }, '/settings/default-llms'],
        [
            'a secret, searched by its name',
            { target_type: 'secret', target_id: '30', target_name: 'OPENAI KEY' },
            '/settings/secrets?search=OPENAI%20KEY',
        ],
        [
            'a member, searched by email',
            { target_type: 'member', target_id: '31', target_name: 'bob@example.com' },
            '/workspace/users?search=bob%40example.com',
        ],
        [
            'a user, searched by email',
            { target_type: 'user', target_id: '32', target_name: 'bob@example.com' },
            '/workspace/users?search=bob%40example.com',
        ],
        [
            'a role, searched by name',
            { target_type: 'role', target_id: '33', target_name: 'Editor' },
            '/workspace/roles?search=Editor',
        ],
        [
            'an API key, searched by name',
            { target_type: 'API key', target_id: '34', target_name: 'CI bot' },
            '/workspace/api-keys?search=CI%20bot',
        ],
        [
            'an organization, searched by name',
            { target_type: 'organization', target_id: '1', target_name: 'Acme' },
            '/workspace/organizations?search=Acme',
        ],
        [
            'a storage file, by its path',
            { target_type: 'storage file', target_id: '30', target_name: 'reports/Q1 summary.pdf' },
            '/storage/files?path=reports%2FQ1%20summary.pdf',
        ],
        [
            'a storage folder, by its path',
            { target_type: 'storage folder', target_id: '31', target_name: 'reports/' },
            '/storage/files?path=reports%2F',
        ],
        [
            'a chat desk',
            { target_type: 'desk', target_id: '0b8f6c1e-2f4d-4a7b-9c55-3f1a2b6d7e90' },
            '/chat-bindings/0b8f6c1e-2f4d-4a7b-9c55-3f1a2b6d7e90',
        ],
        ['a type no page opens', { target_type: 'LLM model', target_id: '2' }, null],
        ['a node by a label no longer recorded', { target_type: 'python node', target_id: '12', ...inFlow }, null],
        ['a start node, which has no panel', { target_type: 'start node', target_id: '15', ...inFlow }, null],
        ['a note', { target_type: 'note', target_id: '16', ...inFlow }, null],
        ['an edge', { target_type: 'edge', target_id: '17', ...inFlow }, null],
        [
            'a node whose parent is not a flow',
            { target_type: 'python code node', target_id: '12', parent_type: 'agent', parent_id: '7' },
            null,
        ],
        ['a node without its flow id', { target_type: 'python code node', target_id: '12', parent_type: 'flow' }, null],
        ['a session without its flow', { target_type: 'session', target_id: '88' }, null],
        [
            'a collection file whose parent is not a collection',
            { target_type: 'collection file', target_id: '50', parent_type: 'agent', parent_id: '7' },
            null,
        ],
        ['Twilio settings without their channel', { target_type: 'Twilio settings', target_id: '60' }, null],
        ['a flow without an id', { target_type: 'flow', target_name: 'Billing' }, null],
        ['a storage file without a path', { target_type: 'storage file', target_id: '30' }, null],
        ['a secret without a name', { target_type: 'secret', target_id: '30' }, null],
        ['no target', {}, null],
    ])('links %s', (_case, fields, expected) => {
        expect(userActionTargetUrl({ ...baseAction, ...fields }, openEverything)).toBe(expected);
    });

    it.each<[string, string]>([
        ['LLM config', 'llm'],
        ['embedding config', 'embedding'],
        ['System One config', 'system-one'],
        ['OpenAI voice config', 'openai-voice'],
        ['ElevenLabs voice config', 'elevenlabs-voice'],
        ['Gemini voice config', 'gemini-voice'],
    ])('links a %s to its LLM library dialog', (type, configType) => {
        expect(userActionTargetUrl({ ...baseAction, target_type: type, target_id: '2' }, openEverything)).toBe(
            `/settings/llm-library?configType=${configType}&configId=2`
        );
    });

    it('links no target once it is deleted', () => {
        expect(
            userActionTargetUrl(
                { ...baseAction, action: 'deleted', target_type: 'flow', target_id: '4', target_name: 'Billing' },
                openEverything
            )
        ).toBeNull();
    });
});

describe('userActionTargetUrl of a target moved to the recycle bin', () => {
    const binned = (target_type: string, target_name: string | null): AuditUserAction => ({
        ...baseAction,
        action: 'moved_to_recycle_bin',
        target_type,
        target_id: '9',
        target_name,
    });

    it.each<[string, string | null, string]>([
        ['flow', 'Q1 billing', '/recycle-bin/flows?search=Q1%20billing'],
        ['agent', 'Researcher', '/recycle-bin/agents?search=Researcher'],
        ['surface', 'Brief', '/recycle-bin/surfaces?search=Brief'],
        ['custom tool', 'Parser', '/recycle-bin/tools?search=Parser&kind=python_tool'],
        ['MCP tool', 'Search', '/recycle-bin/tools?search=Search&kind=mcp_tool'],
        // the bin searches a stored item by its own name, not its path
        ['storage file', 'reports/Q1 summary.pdf', '/recycle-bin/files?search=Q1%20summary.pdf'],
        ['storage folder', 'reports/archive/', '/recycle-bin/files?search=archive'],
        ['knowledge collection', 'Manuals', '/recycle-bin/knowledge-sources?search=Manuals'],
        ['key-value table', 'Prices', '/recycle-bin/key-value-tables?search=Prices'],
        ['secret', 'OPENAI_KEY', '/recycle-bin/secrets?search=OPENAI_KEY'],
        ['voice channel', 'Support line', '/recycle-bin/voice-channels?search=Support%20line'],
        ['webhook trigger', 'orders-in', '/recycle-bin/webhook-triggers?search=orders-in'],
        ['flow', null, '/recycle-bin/flows'],
    ])('links a binned %s named %s to its tab', (type, name, expected) => {
        expect(userActionTargetUrl(binned(type, name), openEverything)).toBe(expected);
    });

    it.each(['python code node', 'LLM config', 'flow version', 'python code tool', 'source collection'])(
        'links no binned %s: no tab lists it',
        (type) => {
            expect(userActionTargetUrl(binned(type, 'Parse'), openEverything)).toBeNull();
        }
    );

    it.each<[string, ResourceCode]>([
        ['flow', ResourceCode.Flows],
        ['surface', ResourceCode.Surfaces],
        ['MCP tool', ResourceCode.Tools],
        ['storage file', ResourceCode.Files],
        ['webhook trigger', ResourceCode.Webhooks],
    ])('links no binned %s without read access to its tab', (type, deniedResource) => {
        expect(userActionTargetUrl(binned(type, 'Item'), pageAccess({ can: denying(deniedResource) }))).toBeNull();
    });
});

describe('a page the viewer may not open', () => {
    // permissionGuard: read access in the active org
    it.each<[string, Partial<AuditUserAction>, ResourceCode]>([
        ['a flow', { target_type: 'flow', target_id: '4' }, ResourceCode.Flows],
        ['a node', { target_type: 'python code node', target_id: '12', ...inFlow }, ResourceCode.Flows],
        ['a session', { target_type: 'session', target_id: '88', ...inFlow }, ResourceCode.Flows],
        ['a surface', { target_type: 'surface', target_id: '5' }, ResourceCode.Agents],
        ['an agent', { target_type: 'agent', target_id: '7' }, ResourceCode.Agents],
        ['a custom tool', { target_type: 'custom tool', target_id: '3' }, ResourceCode.Tools],
        [
            'a collection file',
            { target_type: 'collection file', target_id: '50', ...inCollection },
            ResourceCode.KnowledgeSources,
        ],
        ['an LLM config', { target_type: 'LLM config', target_id: '2' }, ResourceCode.LlmConfigs],
        ['the default LLMs', { target_type: 'default LLMs', target_id: '1' }, ResourceCode.LlmConfigs],
        ['a key-value table', { target_type: 'key-value table', target_id: '8' }, ResourceCode.KeyValueTables],
        ['a venv', { target_type: 'venv', target_id: '9' }, ResourceCode.Venvs],
        ['a webhook trigger', { target_type: 'webhook trigger', target_id: '21' }, ResourceCode.Webhooks],
        ['a voice channel', { target_type: 'voice channel', target_id: '22' }, ResourceCode.Voice],
        ['a storage file', { target_type: 'storage file', target_name: 'notes.txt' }, ResourceCode.Files],
        ['a desk', { target_type: 'desk', target_id: 'desk-1' }, ResourceCode.Chats],
    ])('links no %s without read access to its page', (_case, fields, deniedResource) => {
        const event = { ...baseAction, ...fields };
        expect(userActionTargetUrl(event, pageAccess({ can: denying(deniedResource) }))).toBeNull();
        expect(userActionTargetUrl(event, openEverything)).not.toBeNull();
    });

    it('links no desk while the chat service is off, whatever the access to chats', () => {
        const desk = { ...baseAction, target_type: 'desk', target_id: 'desk-1' };
        expect(userActionTargetUrl(desk, pageAccess({ isChatEnabled: false }))).toBeNull();
    });

    // secretsPermissionGuard: read or create access
    it.each<[string, ActionCode[], boolean]>([
        ['read', [ActionCode.Read], true],
        ['create', [ActionCode.Create], true],
        ['only update', [ActionCode.Update], false],
    ])('links a secret given %s access to secrets: %s', (_case, granted, linked) => {
        const can: CanFunction = (resource, action) => resource !== ResourceCode.Secrets || granted.includes(action);
        const secret = { ...baseAction, target_type: 'secret', target_id: '30', target_name: 'OPENAI_KEY' };
        expect(userActionTargetUrl(secret, pageAccess({ can })) !== null).toBe(linked);
    });

    // workspacePermissionGuard: read access in any org, not only the active one
    it.each<[string, ResourceCode]>([
        ['member', ResourceCode.Memberships],
        ['user', ResourceCode.Memberships],
        ['role', ResourceCode.Roles],
        ['API key', ResourceCode.ApiKeys],
        ['organization', ResourceCode.Organizations],
    ])('links a %s by read access to its workspace tab in any org', (type, resource) => {
        const event = { ...baseAction, target_type: type, target_id: '1', target_name: 'Acme' };
        const deniedHere = denying(resource);
        expect(userActionTargetUrl(event, pageAccess({ can: deniedHere }))).not.toBeNull();
        expect(userActionTargetUrl(event, pageAccess({ canInAnyOrg: deniedHere }))).toBeNull();
    });

    it('links no flow parent without read access to flows', () => {
        expect(
            userActionParentUrl({ ...baseAction, ...inFlow }, pageAccess({ can: denying(ResourceCode.Flows) }))
        ).toBeNull();
    });
});

describe('userActionParentUrl', () => {
    it.each<[string, Partial<AuditUserAction>, string | null]>([
        ['a flow', inFlow, '/flows/4'],
        ['a surface', { parent_type: 'surface', parent_id: '5' }, '/agents?surfaceId=5'],
        ['an agent', { parent_type: 'agent', parent_id: '7' }, '/agents?agentId=7'],
        // e.g. a collection file's collection
        ['a knowledge collection', inCollection, '/storage/knowledge-sources?collection=6'],
        ['a voice channel', { parent_type: 'voice channel', parent_id: '22' }, '/settings/voice?channelId=22'],
        // a record names no grandparent, so the node's flow and the file's collection are unknown
        ['a node', { parent_type: 'agent node', parent_id: '20' }, null],
        ['a collection file', { parent_type: 'collection file', parent_id: '50' }, null],
        ['a flow without an id', { parent_type: 'flow' }, null],
        ['no parent', {}, null],
    ])('links %s', (_case, fields, expected) => {
        expect(userActionParentUrl({ ...baseAction, ...fields }, openEverything)).toBe(expected);
    });

    it('still links the parent of a deleted target', () => {
        expect(
            userActionParentUrl(
                { ...baseAction, action: 'deleted', target_type: 'python code node', ...inFlow },
                openEverything
            )
        ).toBe('/flows/4');
    });
});
