import { ActionCode, ResourceCode } from '@shared/models';
import { flowUrl } from '@shared/utils';

import type { PermissionsService } from '../../../services/auth/permissions.service';
import { RECYCLE_BIN_TABS } from '../../recycle-bin/constants/recycle-bin-tabs.constants';
import { RecycleBinSourceKey } from '../../recycle-bin/models/recycle-bin.model';
import { hasKindSwitch } from '../../recycle-bin/utils/recycle-bin-query.util';
import { AuditUserAction } from '../models/audit-user-action.models';

// The flow nodes as the backend records them, limited to those the flow page opens a panel for by `?nodeId=`: a start
// node, a note and an edge have none, so they get no link. Node ids come from one global sequence, so a backend id
// names one node.
const FLOW_NODE_TYPES = [
    'agent node',
    'audio to text node',
    'classification decision table node',
    'decision table node',
    'end node',
    'file extractor node',
    'key-value node',
    'knowledge retriever node',
    'python code node',
    'schedule trigger node',
    'subflow node',
    'task node',
    'telegram trigger node',
    'webhook trigger node',
];

// The recycle-bin source a binned target of each recorded type lands in.
const RECYCLE_BIN_SOURCE_BY_TYPE = new Map<string, RecycleBinSourceKey>([
    ['flow', 'flow'],
    ['agent', 'agent'],
    ['surface', 'surface'],
    ['custom tool', 'python_tool'],
    ['MCP tool', 'mcp_tool'],
    ['storage file', 'storage'],
    ['storage folder', 'storage'],
    ['knowledge collection', 'collection'],
    ['key-value table', 'key_value_table'],
    ['secret', 'secret'],
    ['voice channel', 'realtime_channel'],
    ['webhook trigger', 'webhook_trigger'],
]);

// The `configType` the LLM library opens each recorded config type by.
const LLM_LIBRARY_CONFIG_TYPES = new Map([
    ['LLM config', 'llm'],
    ['embedding config', 'embedding'],
    ['System One config', 'system-one'],
    ['OpenAI voice config', 'openai-voice'],
    ['ElevenLabs voice config', 'elevenlabs-voice'],
    ['Gemini voice config', 'gemini-voice'],
]);

// What the linked pages' route guards read: the viewer's permissions and whether the chat service runs.
export interface PageAccess {
    permissions: Pick<PermissionsService, 'can' | 'canAny' | 'canInAnyOrg'>;
    isChatEnabled: boolean;
}

// The check a page's route guard makes. A settings or workspace tab's own check implies its parent's (settingsGuard,
// workspaceGuard), so only the tab's is stated.
type PageGuard = (access: PageAccess) => boolean;

interface PageLink {
    url: string;
    guard: PageGuard;
}

// permissionGuard: read access in the active org
const readable =
    (resource: ResourceCode): PageGuard =>
    ({ permissions }) =>
        permissions.can(resource, ActionCode.Read);
// workspacePermissionGuard: read access in any org the viewer belongs to
const readableInAnyOrg =
    (resource: ResourceCode): PageGuard =>
    ({ permissions }) =>
        permissions.canInAnyOrg(resource, ActionCode.Read);
// secretsPermissionGuard: read or create access
const secretsPage: PageGuard = ({ permissions }) =>
    permissions.canAny(ResourceCode.Secrets, [ActionCode.Read, ActionCode.Create]);
// chatEnabledGuard, then permissionGuard
const chatPage: PageGuard = ({ permissions, isChatEnabled }) =>
    isChatEnabled && permissions.can(ResourceCode.Chats, ActionCode.Read);

// the storage page ignores a folder's trailing slash
const storageLink = (path: string): PageLink => ({
    url: `/storage/files?path=${path}`,
    guard: readable(ResourceCode.Files),
});
// a member's and a user's name is their email
const usersLink = (email: string): PageLink => ({
    url: `/workspace/users?search=${email}`,
    guard: readableInAnyOrg(ResourceCode.Memberships),
});
const collectionUrl = (collectionId: string): string => `/storage/knowledge-sources?collection=${collectionId}`;

// Pages that find an object by its (URL-encoded) name.
const PAGE_BY_NAME = new Map<string, (name: string) => PageLink>([
    ['storage file', storageLink],
    ['storage folder', storageLink],
    ['secret', (name) => ({ url: `/settings/secrets?search=${name}`, guard: secretsPage })],
    ['member', usersLink],
    ['user', usersLink],
    ['role', (name) => ({ url: `/workspace/roles?search=${name}`, guard: readableInAnyOrg(ResourceCode.Roles) })],
    [
        'API key',
        (name) => ({ url: `/workspace/api-keys?search=${name}`, guard: readableInAnyOrg(ResourceCode.ApiKeys) }),
    ],
    [
        'organization',
        (name) => ({
            url: `/workspace/organizations?search=${name}`,
            guard: readableInAnyOrg(ResourceCode.Organizations),
        }),
    ],
]);

// Pages that open an object by its (URL-encoded) id.
const PAGE_BY_ID = new Map<string, (id: string) => PageLink>([
    ['flow', (id) => ({ url: flowUrl(id), guard: readable(ResourceCode.Flows) })],
    ['agent', (id) => ({ url: `/agents?agentId=${id}`, guard: readable(ResourceCode.Agents) })],
    ['surface', (id) => ({ url: `/agents?surfaceId=${id}`, guard: readable(ResourceCode.Agents) })],
    ['desk', (id) => ({ url: `/chat-bindings/${id}`, guard: chatPage })],
    ['custom tool', (id) => ({ url: `/tools/custom?toolId=${id}`, guard: readable(ResourceCode.Tools) })],
    ['MCP tool', (id) => ({ url: `/tools/mcp?toolId=${id}`, guard: readable(ResourceCode.Tools) })],
    ['knowledge collection', (id) => ({ url: collectionUrl(id), guard: readable(ResourceCode.KnowledgeSources) })],
    [
        'key-value table',
        (id) => ({ url: `/storage/key-value-tables?tableId=${id}`, guard: readable(ResourceCode.KeyValueTables) }),
    ],
    ['venv', (id) => ({ url: `/venvs?venvId=${id}`, guard: readable(ResourceCode.Venvs) })],
    [
        'webhook trigger',
        (id) => ({ url: `/settings/webhook-triggers?triggerId=${id}`, guard: readable(ResourceCode.Webhooks) }),
    ],
    ['voice channel', (id) => ({ url: `/settings/voice?channelId=${id}`, guard: readable(ResourceCode.Voice) })],
    // one per org, so the page needs no id
    ['default LLMs', () => ({ url: '/settings/default-llms', guard: readable(ResourceCode.LlmConfigs) })],
    ...[...LLM_LIBRARY_CONFIG_TYPES].map(([type, configType]): [string, (id: string) => PageLink] => [
        type,
        (id) => ({
            url: `/settings/llm-library?configType=${configType}&configId=${id}`,
            guard: readable(ResourceCode.LlmConfigs),
        }),
    ]),
]);

interface ChildPage {
    parentType: string;
    link: (parentId: string, id: string) => PageLink;
}

const nodePage: ChildPage = {
    parentType: 'flow',
    link: (flowId, id) => ({ url: `${flowUrl(flowId)}?nodeId=${id}`, guard: readable(ResourceCode.Flows) }),
};

// Objects that open on their parent's page, so only under the parent type that page shows.
const PAGE_BY_PARENT = new Map<string, ChildPage>([
    ...FLOW_NODE_TYPES.map((type): [string, ChildPage] => [type, nodePage]),
    [
        'session',
        {
            parentType: 'flow',
            link: (flowId, id) => ({ url: `/graph/${flowId}/session/${id}`, guard: readable(ResourceCode.Flows) }),
        },
    ],
    [
        'voice settings',
        {
            parentType: 'agent',
            link: (agentId) => ({ url: `/agents?agentId=${agentId}`, guard: readable(ResourceCode.Agents) }),
        },
    ],
    [
        'collection file',
        {
            parentType: 'knowledge collection',
            link: (collectionId) => ({
                url: collectionUrl(collectionId),
                guard: readable(ResourceCode.KnowledgeSources),
            }),
        },
    ],
    [
        'naive RAG',
        {
            parentType: 'knowledge collection',
            link: (collectionId, id) => ({
                url: `${collectionUrl(collectionId)}&rag=${id}`,
                guard: readable(ResourceCode.KnowledgeSources),
            }),
        },
    ],
    [
        'graph RAG',
        {
            parentType: 'knowledge collection',
            link: (collectionId) => ({
                url: collectionUrl(collectionId),
                guard: readable(ResourceCode.KnowledgeSources),
            }),
        },
    ],
    [
        'Twilio settings',
        {
            parentType: 'voice channel',
            link: (channelId) => ({
                url: `/settings/voice?channelId=${channelId}`,
                guard: readable(ResourceCode.Voice),
            }),
        },
    ],
]);

interface LinkedObject {
    type: string | null;
    id: string | null;
    name: string | null;
    parentType: string | null;
    parentId: string | null;
}

// The app page that opens this object, or null when none does.
function objectPage({ type, id, name, parentType, parentId }: LinkedObject): PageLink | null {
    const byName = PAGE_BY_NAME.get(type ?? '');
    if (byName) {
        return name ? byName(encodeURIComponent(name)) : null;
    }
    if (!id) {
        return null;
    }
    const byId = PAGE_BY_ID.get(type ?? '');
    if (byId) {
        return byId(encodeURIComponent(id));
    }
    const child = PAGE_BY_PARENT.get(type ?? '');
    return child && parentId && parentType === child.parentType
        ? child.link(encodeURIComponent(parentId), encodeURIComponent(id))
        : null;
}

// The object's page, when the viewer passes that page's route guard.
function objectUrl(object: LinkedObject, access: PageAccess): string | null {
    const page = objectPage(object);
    return page && page.guard(access) ? page.url : null;
}

export function isMovedToRecycleBin(event: AuditUserAction): boolean {
    return event.action === 'moved_to_recycle_bin';
}

// A deleted target is gone; a binned one opens in its recycle-bin tab.
export function userActionTargetUrl(event: AuditUserAction, access: PageAccess): string | null {
    if (event.action === 'deleted') {
        return null;
    }
    if (isMovedToRecycleBin(event)) {
        return recycleBinUrl(event, access);
    }
    return objectUrl(
        {
            type: event.target_type,
            id: event.target_id,
            name: event.target_name,
            parentType: event.parent_type,
            parentId: event.parent_id,
        },
        access
    );
}

// The target's recycle-bin tab, searched to its name and switched to its bin on a tab with two (Tools).
function recycleBinUrl({ target_type, target_name }: AuditUserAction, access: PageAccess): string | null {
    const source = RECYCLE_BIN_SOURCE_BY_TYPE.get(target_type ?? '');
    const tab = RECYCLE_BIN_TABS.find((candidate) => source !== undefined && candidate.sources.includes(source));
    if (source === undefined || tab === undefined || !access.permissions.can(tab.resource, ActionCode.Read)) {
        return null;
    }
    // The bin searches a stored file or folder by its own name, not its path; a folder's path ends with `/`.
    const searchText = source === 'storage' ? target_name?.split('/').filter(Boolean).at(-1) : target_name;
    const query = [
        searchText ? `search=${encodeURIComponent(searchText)}` : null,
        hasKindSwitch(tab) ? `kind=${source}` : null,
    ].filter((part) => part !== null);
    return `/recycle-bin/${tab.key}${query.length > 0 ? `?${query.join('&')}` : ''}`;
}

// a record names no grandparent, so a parent that is itself a node or a session gets no link
export function userActionParentUrl(event: AuditUserAction, access: PageAccess): string | null {
    return objectUrl(
        { type: event.parent_type, id: event.parent_id, name: event.parent_name, parentType: null, parentId: null },
        access
    );
}
