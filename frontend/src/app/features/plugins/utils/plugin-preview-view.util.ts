import { getRelativeTime } from '@shared/utils';

import { PluginPreviewItemView, PluginPreviewListView } from '../models/plugin-preview-view.model';
import { PluginPurgePreviewOrganization } from '../models/plugin-purge-preview.model';
import {
    PluginDefaultModelReference,
    PluginOwnedResourceCount,
    PluginPreviewList,
    PluginPreviewSession,
} from '../models/plugin-suspend-preview.model';
import {
    PLUGIN_DEFAULT_MODEL_SETTING_LABELS,
    PLUGIN_GRANT_STATE_LABELS,
    PLUGIN_PREVIEW_SESSION_STATUS_LABELS,
} from './plugin-display.util';

// How the dialogs that preview an action (suspend, delete data, uninstall, delete a plugin) turn the server's lists
// into the lines of `app-plugin-preview-section`. One place, so the dialogs cannot show the same thing differently.

/** The items the server sent, and how many more it counted: "and N more". */
export function toPreviewListView<Item>(
    list: PluginPreviewList<Item>,
    toItem: (item: Item) => PluginPreviewItemView
): PluginPreviewListView {
    return { items: list.items.map(toItem), moreCount: Math.max(0, list.total - list.items.length) };
}

/** What the plugin owns, one line per kind with its count beside it. */
export function ownedResourcesListView(counts: readonly PluginOwnedResourceCount[]): PluginPreviewListView {
    return {
        items: counts.map((owned) => ({ key: owned.model, name: owned.label, detail: String(owned.count) })),
        moreCount: 0,
    };
}

/** The default-model settings that point at the plugin's configs: "Agent LLM → Weather summaries". */
export function defaultModelsListView(references: readonly PluginDefaultModelReference[]): PluginPreviewListView {
    return { items: references.map(defaultModelItem), moreCount: 0 };
}

/** Anything listed by its id and name alone: a flow, a realtime agent, a voice channel. */
export function previewNamedItem(item: { id: number; name: string }): PluginPreviewItemView {
    return { key: String(item.id), name: item.name, detail: null };
}

/** A running session: its flow, its status and when it started. */
export function previewSessionItem(session: PluginPreviewSession): PluginPreviewItemView {
    const status = PLUGIN_PREVIEW_SESSION_STATUS_LABELS[session.status];
    return {
        key: String(session.id),
        name: session.flow.name,
        detail: `${status} · started ${getRelativeTime(session.created_at)}`,
    };
}

/** An organization the plugin is granted to: "Acme · Active · 2 owned". */
export function previewOrganizationItem(item: PluginPurgePreviewOrganization): PluginPreviewItemView {
    return {
        key: String(item.grant_id),
        name: item.organization.name,
        detail: `${PLUGIN_GRANT_STATE_LABELS[item.state]} · ${item.owned_resource_count} owned`,
    };
}

function defaultModelItem(reference: PluginDefaultModelReference): PluginPreviewItemView {
    return {
        key: reference.setting,
        name: `${PLUGIN_DEFAULT_MODEL_SETTING_LABELS[reference.setting]} → ${reference.config.name}`,
        detail: null,
    };
}
