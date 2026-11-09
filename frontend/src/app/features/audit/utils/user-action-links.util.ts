import { ResourceCode } from '@shared/models';
import { flowUrl } from '@shared/utils';

import { RECYCLE_BIN_TABS } from '../../recycle-bin/constants/recycle-bin-tabs.constants';
import { RecycleBinSourceKey } from '../../recycle-bin/models/recycle-bin.model';
import { hasKindSwitch } from '../../recycle-bin/utils/recycle-bin-query.util';
import { AuditUserAction } from '../models/audit-user-action.models';

// The flow nodes as the backend records them (each node model's verbose_name), limited to those the flow page
// opens a panel for by `?nodeId=`: a start node, a note and an edge have none, so they get no link. Node ids come from
// one global sequence, so a backend id names one node.
const FLOW_NODE_TYPES = new Set([
    'agent node',
    'audio transcription node',
    'classification decision table node',
    'decision table node',
    'end node',
    'file extractor node',
    'key value node',
    'knowledge node',
    'python node',
    'schedule trigger node',
    'sub graph node',
    'task node',
    'telegram trigger node',
    'webhook trigger node',
]);

// The recycle-bin source a binned target of each recorded type lands in.
const RECYCLE_BIN_SOURCE_BY_TYPE = new Map<string, RecycleBinSourceKey>([
    ['flow', 'flow'],
    ['agent', 'agent'],
    ['surface', 'surface'],
    ['python code tool', 'python_tool'],
    ['MCP tool', 'mcp_tool'],
    ['storage file', 'storage'],
    ['storage folder', 'storage'],
    ['source collection', 'collection'],
    ['key value table', 'key_value_table'],
    ['secret', 'secret'],
    ['realtime channel', 'realtime_channel'],
    ['webhook trigger', 'webhook_trigger'],
]);

interface LinkedObject {
    type: string | null;
    id: string | null;
    name: string | null;
    parentType: string | null;
    parentId: string | null;
}

// Whether the viewer may open the page whose route is guarded by read access to `resource`.
export type CanOpenPage = (resource: ResourceCode) => boolean;

// The app page that opens this object, or null when none does or the viewer may not open it.
function objectUrl({ type, id, name, parentType, parentId }: LinkedObject, canOpen: CanOpenPage): string | null {
    const allowed = (url: string, resource: ResourceCode): string | null => (canOpen(resource) ? url : null);
    if (type === 'storage file' || type === 'storage folder') {
        // the name is the org-relative path; the storage page ignores a folder's trailing slash
        return name ? allowed(`/storage/files?path=${encodeURIComponent(name)}`, ResourceCode.Files) : null;
    }
    if (!id) {
        return null;
    }
    const encodedId = encodeURIComponent(id);
    if (type === 'flow') {
        return allowed(flowUrl(id), ResourceCode.Flows);
    }
    if (type === 'surface') {
        return allowed(`/agents?surfaceId=${encodedId}`, ResourceCode.Agents);
    }
    if (type === 'desk') {
        return allowed(`/chat-bindings/${encodedId}`, ResourceCode.Chats);
    }
    // a node and a session open only inside their flow
    if (parentType !== 'flow' || !parentId) {
        return null;
    }
    if (FLOW_NODE_TYPES.has(type ?? '')) {
        return allowed(`${flowUrl(parentId)}?nodeId=${encodedId}`, ResourceCode.Flows);
    }
    if (type === 'session') {
        return allowed(`/graph/${encodeURIComponent(parentId)}/session/${encodedId}`, ResourceCode.Flows);
    }
    return null;
}

export function isMovedToRecycleBin(event: AuditUserAction): boolean {
    return event.action === 'moved_to_recycle_bin';
}

// A deleted target is gone; a binned one opens in its recycle-bin tab.
export function userActionTargetUrl(event: AuditUserAction, canOpen: CanOpenPage): string | null {
    if (event.action === 'deleted') {
        return null;
    }
    if (isMovedToRecycleBin(event)) {
        return recycleBinUrl(event, canOpen);
    }
    return objectUrl(
        {
            type: event.target_type,
            id: event.target_id,
            name: event.target_name,
            parentType: event.parent_type,
            parentId: event.parent_id,
        },
        canOpen
    );
}

// The target's recycle-bin tab, searched to its name and switched to its bin on a tab with two (Tools).
function recycleBinUrl({ target_type, target_name }: AuditUserAction, canOpen: CanOpenPage): string | null {
    const source = RECYCLE_BIN_SOURCE_BY_TYPE.get(target_type ?? '');
    const tab = RECYCLE_BIN_TABS.find((candidate) => source !== undefined && candidate.sources.includes(source));
    if (source === undefined || tab === undefined || !canOpen(tab.resource)) {
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
export function userActionParentUrl(event: AuditUserAction, canOpen: CanOpenPage): string | null {
    return objectUrl(
        { type: event.parent_type, id: event.parent_id, name: event.parent_name, parentType: null, parentId: null },
        canOpen
    );
}
