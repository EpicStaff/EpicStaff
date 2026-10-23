import { PluginGrantState, PluginOrganizationRef } from './plugin-admin.model';

/** The first items of a list (at most 100) and how many there are in all. */
export interface PluginPreviewList<Item> {
    total: number;
    items: Item[];
}

export interface PluginPreviewFlow {
    id: number;
    name: string;
}

/** An agent definition or a voice channel. */
export interface PluginPreviewNamedItem {
    id: number;
    name: string;
}

export type PluginPreviewSessionStatus = 'pending' | 'run' | 'wait_for_user';

export interface PluginPreviewSession {
    id: number;
    flow: PluginPreviewFlow;
    status: PluginPreviewSessionStatus;
    created_at: string;
}

export type PluginPreviewTriggerKind = 'schedule' | 'webhook' | 'telegram';

export interface PluginPreviewTrigger {
    kind: PluginPreviewTriggerKind;
    node_id: number;
    node_name: string;
    flow: PluginPreviewFlow;
}

/** A field of the organization's default models. */
export type PluginDefaultModelSetting =
    | 'agent_llm_config'
    | 'agent_fcm_llm_config'
    | 'voice_llm_config'
    | 'transcription_llm_config'
    | 'project_manager_llm_config'
    | 'memory_embedding_config'
    | 'memory_llm_config';

/** A default-model setting that points at a config the plugin owns. */
export interface PluginDefaultModelReference {
    setting: PluginDefaultModelSetting;
    config: { id: number; name: string };
}

/** How many rows of one kind the plugin owns in the organization: `{ model: 'tables.Graph', label: 'Flows', … }`. */
export interface PluginOwnedResourceCount {
    model: string;
    label: string;
    count: number;
}

/**
 * What suspending a grant stops in its organization (`GET …/grants/{id}/suspend-preview/`): the flows that use
 * something the plugin owns, split into the organization's and the plugin's own, their running sessions and
 * triggers, the realtime agents and voice channels, and the default-model settings that point at the plugin's configs.
 */
export interface PluginSuspendPreview {
    grant: { id: number; state: PluginGrantState };
    plugin: { identifier: string; name: string };
    organization: PluginOrganizationRef;
    /** Now plus the grace period. */
    data_kept_until: string;
    /** Sorted by label. */
    owned_resources: PluginOwnedResourceCount[];
    flows: { organization: PluginPreviewList<PluginPreviewFlow>; plugin: PluginPreviewList<PluginPreviewFlow> };
    running_sessions: PluginPreviewList<PluginPreviewSession>;
    triggers: PluginPreviewList<PluginPreviewTrigger>;
    realtime_agents: PluginPreviewList<PluginPreviewNamedItem>;
    voice_channels: PluginPreviewList<PluginPreviewNamedItem>;
    default_models: PluginDefaultModelReference[];
}
