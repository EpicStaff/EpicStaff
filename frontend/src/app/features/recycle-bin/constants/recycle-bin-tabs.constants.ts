import { ResourceCode } from '@shared/models';

import { RecycleBinTabDefinition, RecycleBinTabKey } from '../models/recycle-bin.model';

export const RECYCLE_BIN_TAB_BY_KEY: Record<RecycleBinTabKey, RecycleBinTabDefinition> = {
    flows: {
        key: 'flows',
        label: 'Flows',
        resource: ResourceCode.Flows,
        sources: ['flow'],
        pluralNoun: 'flows',
        countColumn: { label: 'Nodes' },
    },
    agents: {
        key: 'agents',
        label: 'Agents',
        resource: ResourceCode.Agents,
        sources: ['agent'],
        pluralNoun: 'agents',
        countColumn: { label: 'Surfaces' },
    },
    surfaces: {
        key: 'surfaces',
        label: 'Surfaces',
        resource: ResourceCode.Surfaces,
        sources: ['surface'],
        pluralNoun: 'surfaces',
    },
    tools: {
        key: 'tools',
        label: 'Tools',
        resource: ResourceCode.Tools,
        sources: ['python_tool', 'mcp_tool'],
        pluralNoun: 'tools',
    },
    files: {
        key: 'files',
        label: 'Files',
        resource: ResourceCode.Files,
        sources: ['storage'],
        pluralNoun: 'files and folders',
    },
    'knowledge-sources': {
        key: 'knowledge-sources',
        label: 'Knowledge sources',
        resource: ResourceCode.KnowledgeSources,
        sources: ['collection'],
        pluralNoun: 'collections',
    },
    'key-value-tables': {
        key: 'key-value-tables',
        label: 'Key-value tables',
        resource: ResourceCode.KeyValueTables,
        sources: ['key_value_table'],
        pluralNoun: 'key-value tables',
        countColumn: { label: 'Keys' },
    },
    secrets: {
        key: 'secrets',
        label: 'Secrets',
        resource: ResourceCode.Secrets,
        sources: ['secret'],
        pluralNoun: 'secrets',
    },
    'voice-channels': {
        key: 'voice-channels',
        label: 'Voice channels',
        resource: ResourceCode.Voice,
        sources: ['realtime_channel'],
        pluralNoun: 'voice channels',
    },
    'webhook-triggers': {
        key: 'webhook-triggers',
        label: 'Webhook triggers',
        resource: ResourceCode.Webhooks,
        sources: ['webhook_trigger'],
        pluralNoun: 'webhook triggers',
    },
};

/** Tab order on the page, and the order the default tab is picked in. */
export const RECYCLE_BIN_TABS: readonly RecycleBinTabDefinition[] = [
    RECYCLE_BIN_TAB_BY_KEY.flows,
    RECYCLE_BIN_TAB_BY_KEY.agents,
    RECYCLE_BIN_TAB_BY_KEY.surfaces,
    RECYCLE_BIN_TAB_BY_KEY.tools,
    RECYCLE_BIN_TAB_BY_KEY.files,
    RECYCLE_BIN_TAB_BY_KEY['knowledge-sources'],
    RECYCLE_BIN_TAB_BY_KEY['key-value-tables'],
    RECYCLE_BIN_TAB_BY_KEY.secrets,
    RECYCLE_BIN_TAB_BY_KEY['voice-channels'],
    RECYCLE_BIN_TAB_BY_KEY['webhook-triggers'],
];
