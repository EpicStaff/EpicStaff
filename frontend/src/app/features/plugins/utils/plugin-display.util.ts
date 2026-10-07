import { ReviewItem } from '../../../core/models/review-item.model';
import {
    PluginAccessAction,
    PluginAccessTargetType,
    PluginInspectContentItem,
    PluginMissingPermission,
    PluginResourceType,
    PluginSecretDestination,
    PluginSummary,
} from '../models/plugin.model';

interface ResourceTypeLabel {
    singular: string;
    plural: string;
}

/** Display order and names of plugin resource types. */
export const PLUGIN_RESOURCE_TYPE_LABELS: Record<PluginResourceType, ResourceTypeLabel> = {
    flow: { singular: 'Flow', plural: 'Flows' },
    agent_definition: { singular: 'Agent', plural: 'Agents' },
    surface: { singular: 'Agent surface', plural: 'Agent surfaces' },
    python_code_tool: { singular: 'Python tool', plural: 'Python tools' },
    mcp_tool: { singular: 'MCP tool', plural: 'MCP tools' },
    webhook_trigger: { singular: 'Webhook trigger', plural: 'Webhook triggers' },
    key_value_table: { singular: 'Key-value table', plural: 'Key-value tables' },
    llm_model: { singular: 'LLM model', plural: 'LLM models' },
    llm_config: { singular: 'LLM configuration', plural: 'LLM configurations' },
    embedding_model: { singular: 'Embedding model', plural: 'Embedding models' },
    embedding_config: { singular: 'Embedding configuration', plural: 'Embedding configurations' },
    source_collection: { singular: 'Knowledge collection', plural: 'Knowledge collections' },
    storage_file: { singular: 'File', plural: 'Files' },
    secret: { singular: 'Secret', plural: 'Secrets' },
};

const RESOURCE_TYPE_ORDER = Object.keys(PLUGIN_RESOURCE_TYPE_LABELS);

export interface PluginContentGroup {
    type: string;
    label: string;
    items: PluginContentLine[];
}

export interface PluginContentLine {
    name: string;
    detail: string | null;
}

export interface PluginSecretDestinationLine {
    /** e.g. "Sent to: api.example.com (custom endpoint)" or "Sent to: openai's standard endpoint". */
    target: string;
    /** The config or tool that sends it, e.g. "by LLM configuration 'Chat Bot GPT-4o mini'". */
    via: string;
    /** Any explicit host counts as custom: the value leaves for an endpoint the plugin chose. */
    isCustomHost: boolean;
}

/** Only PNG / SVG data URLs (the contract's two icon forms) are ever bound to `<img [src]>`. */
export function isPluginIconUrl(url: string | null | undefined): boolean {
    return !!url && (url.startsWith('data:image/png;base64,') || url.startsWith('data:image/svg+xml;base64,'));
}

export function resourceTypeLabel(type: string, count: number): string {
    const label = PLUGIN_RESOURCE_TYPE_LABELS[type as PluginResourceType];
    if (!label) return humanize(type);
    return count === 1 ? label.singular : label.plural;
}

export function pluginStatusLabel(plugin: Pick<PluginSummary, 'status' | 'status_reason'>): string {
    switch (plugin.status) {
        case 'preparing':
            return 'Preparing knowledge…';
        case 'ready':
            return 'Ready';
        case 'needs_attention':
            return plugin.status_reason ? `Needs attention: ${plugin.status_reason}` : 'Needs attention';
        case 'suspended':
            return 'Suspended';
        default:
            return humanize(plugin.status);
    }
}

/**
 * Plain words for one access entry, e.g. "Run flow 'Chat Bot', read its sessions and stop its sessions"
 * or "Read key-value table 'chat_admin__conversations'". An entry without a `type` is a flow.
 */
export function describePluginAccess(entry: {
    type?: PluginAccessTargetType;
    resource_name: string | null;
    actions: PluginAccessAction[];
}): string {
    if (entry.type === 'key_value_table') return describeTableAccess(entry.resource_name, entry.actions);
    const target = entry.resource_name ? `flow '${entry.resource_name}'` : 'a flow that no longer exists';
    const sessionVerbs = entry.actions
        .filter((action) => action !== 'run')
        .map((action) => SESSION_ACTION_VERBS[action] ?? humanize(action));

    if (entry.actions.includes('run')) {
        const rest = sessionVerbs.map((verb) => `${verb} its sessions`);
        return capitalize(joinWords([`run ${target}`, ...rest]));
    }
    if (sessionVerbs.length === 0) return capitalize(`use ${target}`);
    return capitalize(`${joinWords(sessionVerbs)} the sessions of ${target}`);
}

/** e.g. "create secrets", "create knowledge sources". */
export function describeMissingPermission(permission: PluginMissingPermission): string {
    return `${permission.action} ${humanize(permission.resource_type).toLowerCase()}`;
}

export function describeReviewItem(item: ReviewItem): string {
    switch (item.kind) {
        case 'python_code_tool':
            return `Python tool '${item.name}'`;
        case 'mcp_tool':
            return `MCP tool '${item.name}' (${item.transport})`;
        case 'flow_node':
            return `${item.node_type} node${item.node_name ? ` '${item.node_name}'` : ''} in flow '${item.flow_name}'`;
    }
}

export function describeSecretDestination(destination: PluginSecretDestination): PluginSecretDestinationLine {
    const via = `by ${resourceTypeLabel(destination.resource_type, 1)} '${destination.name}'`;
    if (destination.host !== null) {
        return { target: `Sent to: ${destination.host} (custom endpoint)`, via, isCustomHost: true };
    }
    const provider = destination.provider ?? 'its provider';
    return { target: `Sent to: ${provider}'s standard endpoint`, via, isCustomHost: false };
}

/** Groups the inspect `contents` by type, in a stable display order. */
export function groupPluginContents(contents: PluginInspectContentItem[]): PluginContentGroup[] {
    const groups = new Map<string, PluginContentLine[]>();
    for (const item of contents) {
        const lines = groups.get(item.type) ?? [];
        lines.push({ name: item.name, detail: describeDocuments(item.documents) });
        groups.set(item.type, lines);
    }
    return [...groups.entries()]
        .sort(([first], [second]) => typeRank(first) - typeRank(second))
        .map(([type, items]) => ({ type, label: resourceTypeLabel(type, items.length), items }));
}

const SESSION_ACTION_VERBS: Partial<Record<PluginAccessAction, string>> = {
    'sessions.read': 'read',
    'sessions.stop': 'stop',
};

/** Key-value tables are read-only to a plugin page; `read` is the only action. */
function describeTableAccess(resourceName: string | null, actions: PluginAccessAction[]): string {
    const target = resourceName ? `key-value table '${resourceName}'` : 'a key-value table that no longer exists';
    const verbs = actions.map((action) => (action === 'read' ? 'read' : humanize(action).toLowerCase()));
    return capitalize(`${verbs.length ? joinWords(verbs) : 'use'} ${target}`);
}

function describeDocuments(documents: string[] | undefined): string | null {
    if (!documents?.length) return null;
    const noun = documents.length === 1 ? 'document' : 'documents';
    return `${documents.length} ${noun}: ${documents.join(', ')}`;
}

function typeRank(type: string): number {
    const index = RESOURCE_TYPE_ORDER.indexOf(type);
    return index === -1 ? RESOURCE_TYPE_ORDER.length : index;
}

function joinWords(words: string[]): string {
    if (words.length <= 1) return words.join('');
    return `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`;
}

function humanize(text: string): string {
    return capitalize(text.replaceAll('_', ' ').replaceAll('.', ' '));
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}
