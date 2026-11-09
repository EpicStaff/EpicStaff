import { ResourceCode } from '@shared/models';

import { AuditUserAction } from '../models/audit-user-action.models';
import { userActionParentUrl, userActionTargetUrl } from './user-action-links.util';

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

const canOpenEverything = () => true;

const inFlow = { parent_type: 'flow', parent_id: '4', parent_name: 'Billing' };

describe('userActionTargetUrl', () => {
    it.each<[string, Partial<AuditUserAction>, string | null]>([
        ['a flow', { target_type: 'flow', target_id: '4' }, '/flows/4'],
        ['a python node in its flow', { target_type: 'python node', target_id: '12', ...inFlow }, '/flows/4?nodeId=12'],
        [
            'a subflow node in its flow',
            { target_type: 'sub graph node', target_id: '13', ...inFlow },
            '/flows/4?nodeId=13',
        ],
        [
            'a classification decision table node in its flow',
            { target_type: 'classification decision table node', target_id: '14', ...inFlow },
            '/flows/4?nodeId=14',
        ],
        ['a session in its flow', { target_type: 'session', target_id: '88', ...inFlow }, '/graph/4/session/88'],
        ['a surface', { target_type: 'surface', target_id: '5' }, '/agents?surfaceId=5'],
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
        ['a type no page opens', { target_type: 'LLM config', target_id: '2' }, null],
        ['a start node, which has no panel', { target_type: 'start node', target_id: '15', ...inFlow }, null],
        ['a note', { target_type: 'graph note', target_id: '16', ...inFlow }, null],
        ['an edge', { target_type: 'edge', target_id: '17', ...inFlow }, null],
        [
            'a node whose parent is not a flow',
            { target_type: 'python node', target_id: '12', parent_type: 'agent', parent_id: '7' },
            null,
        ],
        ['a node without its flow id', { target_type: 'python node', target_id: '12', parent_type: 'flow' }, null],
        ['a session without its flow', { target_type: 'session', target_id: '88' }, null],
        ['a flow without an id', { target_type: 'flow', target_name: 'Billing' }, null],
        ['a storage file without a path', { target_type: 'storage file', target_id: '30' }, null],
        ['no target', {}, null],
    ])('links %s', (_case, fields, expected) => {
        expect(userActionTargetUrl({ ...baseAction, ...fields }, canOpenEverything)).toBe(expected);
    });

    it('links no target once it is deleted', () => {
        expect(
            userActionTargetUrl(
                { ...baseAction, action: 'deleted', target_type: 'flow', target_id: '4', target_name: 'Billing' },
                canOpenEverything
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
        ['python code tool', 'Parser', '/recycle-bin/tools?search=Parser&kind=python_tool'],
        ['MCP tool', 'Search', '/recycle-bin/tools?search=Search&kind=mcp_tool'],
        // the bin searches a stored item by its own name, not its path
        ['storage file', 'reports/Q1 summary.pdf', '/recycle-bin/files?search=Q1%20summary.pdf'],
        ['storage folder', 'reports/archive/', '/recycle-bin/files?search=archive'],
        ['source collection', 'Manuals', '/recycle-bin/knowledge-sources?search=Manuals'],
        ['key value table', 'Prices', '/recycle-bin/key-value-tables?search=Prices'],
        ['secret', 'OPENAI_KEY', '/recycle-bin/secrets?search=OPENAI_KEY'],
        ['realtime channel', 'Support line', '/recycle-bin/voice-channels?search=Support%20line'],
        ['webhook trigger', 'orders-in', '/recycle-bin/webhook-triggers?search=orders-in'],
        ['flow', null, '/recycle-bin/flows'],
    ])('links a binned %s named %s to its tab', (type, name, expected) => {
        expect(userActionTargetUrl(binned(type, name), canOpenEverything)).toBe(expected);
    });

    it.each(['python node', 'LLM config', 'flow version'])('links no binned %s: no tab lists it', (type) => {
        expect(userActionTargetUrl(binned(type, 'Parse'), canOpenEverything)).toBeNull();
    });

    it.each<[string, ResourceCode]>([
        ['flow', ResourceCode.Flows],
        ['surface', ResourceCode.Surfaces],
        ['MCP tool', ResourceCode.Tools],
        ['storage file', ResourceCode.Files],
        ['webhook trigger', ResourceCode.Webhooks],
    ])('links no binned %s without read access to its tab', (type, deniedResource) => {
        expect(userActionTargetUrl(binned(type, 'Item'), (resource) => resource !== deniedResource)).toBeNull();
    });
});

describe('a page the viewer may not open', () => {
    it.each<[string, Partial<AuditUserAction>, ResourceCode]>([
        ['a flow', { target_type: 'flow', target_id: '4' }, ResourceCode.Flows],
        ['a node', { target_type: 'python node', target_id: '12', ...inFlow }, ResourceCode.Flows],
        ['a session', { target_type: 'session', target_id: '88', ...inFlow }, ResourceCode.Flows],
        ['a surface', { target_type: 'surface', target_id: '5' }, ResourceCode.Agents],
        ['a storage file', { target_type: 'storage file', target_name: 'notes.txt' }, ResourceCode.Files],
        ['a desk', { target_type: 'desk', target_id: 'desk-1' }, ResourceCode.Chats],
    ])('links no %s without read access to its page', (_case, fields, deniedResource) => {
        const canOpen = (resource: ResourceCode) => resource !== deniedResource;
        expect(userActionTargetUrl({ ...baseAction, ...fields }, canOpen)).toBeNull();
        expect(userActionTargetUrl({ ...baseAction, ...fields }, canOpenEverything)).not.toBeNull();
    });

    it('links no flow parent without read access to flows', () => {
        expect(
            userActionParentUrl({ ...baseAction, ...inFlow }, (resource) => resource !== ResourceCode.Flows)
        ).toBeNull();
    });
});

describe('userActionParentUrl', () => {
    it.each<[string, Partial<AuditUserAction>, string | null]>([
        ['a flow', inFlow, '/flows/4'],
        ['a surface', { parent_type: 'surface', parent_id: '5' }, '/agents?surfaceId=5'],
        ['an agent, which no page opens by id', { parent_type: 'agent', parent_id: '7' }, null],
        // a record names no grandparent, so the node's flow is unknown
        ['a node', { parent_type: 'agent node', parent_id: '20' }, null],
        ['a flow without an id', { parent_type: 'flow' }, null],
        ['no parent', {}, null],
    ])('links %s', (_case, fields, expected) => {
        expect(userActionParentUrl({ ...baseAction, ...fields }, canOpenEverything)).toBe(expected);
    });

    it('still links the parent of a deleted target', () => {
        expect(
            userActionParentUrl(
                { ...baseAction, action: 'deleted', target_type: 'python node', ...inFlow },
                canOpenEverything
            )
        ).toBe('/flows/4');
    });
});
