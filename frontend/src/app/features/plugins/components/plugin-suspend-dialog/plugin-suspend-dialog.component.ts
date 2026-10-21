import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent, LoadingSpinnerComponent } from '@shared/components';
import { getRelativeTime } from '@shared/utils';
import { finalize } from 'rxjs';

import { PluginGrant } from '../../models/plugin-admin.model';
import {
    PluginDefaultModelReference,
    PluginPreviewFlow,
    PluginPreviewList,
    PluginPreviewNamedItem,
    PluginPreviewSession,
    PluginPreviewTrigger,
    PluginSuspendPreview,
} from '../../models/plugin-suspend-preview.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    PLUGIN_DEFAULT_MODEL_SETTING_LABELS,
    PLUGIN_DEFAULT_MODEL_SETTINGS_ON_SETTINGS_PAGE,
    PLUGIN_PREVIEW_SESSION_STATUS_LABELS,
    PLUGIN_PREVIEW_TRIGGER_KIND_LABELS,
} from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import {
    PluginPreviewItemView,
    PluginPreviewListView,
    PluginPreviewSectionComponent,
} from '../plugin-preview-section/plugin-preview-section.component';

export interface PluginSuspendDialogData {
    identifier: string;
    pluginName: string;
    grant: PluginGrant;
}

/** The dialog's title element; pass it as `ariaLabelledBy` when opening the dialog. */
export const PLUGIN_SUSPEND_DIALOG_TITLE_ID = 'plugin-suspend-dialog-title';

/** Under the default-model settings that point at the plugin's configs. */
export const PLUGIN_DEFAULT_MODELS_HINT =
    'New agents and features outside runs, such as the flow assistant, keep using these settings.';

/** Added to the hint only when a listed setting is one the Default LLMs page can change. */
export const PLUGIN_DEFAULT_MODELS_REPOINT_HINT = 'Repoint them in Settings → Default LLMs.';

/** The preview as the dialog's sections show it. */
interface SuspendPreviewView {
    owned: PluginPreviewListView;
    organizationFlows: PluginPreviewListView;
    pluginFlows: PluginPreviewListView;
    sessions: PluginPreviewListView;
    triggers: PluginPreviewListView;
    realtimeAgents: PluginPreviewListView;
    voiceChannels: PluginPreviewListView;
    defaultModels: PluginPreviewListView;
    defaultModelsHint: string;
    dataKeptUntil: string;
}

/**
 * Suspends a plugin in one organization after showing what that stops: what the plugin owns there, the
 * organization's flows and the plugin's own flows that will stop, their running sessions and triggers, the realtime
 * agents and voice channels, the default-model settings that point at the plugin's configs, and until when the data is
 * kept. Suspension is undone by Resume, so no typed phrase is asked for. Closes with the suspended grant.
 */
@Component({
    selector: 'app-plugin-suspend-dialog',
    imports: [AppSvgIconComponent, ButtonComponent, DatePipe, LoadingSpinnerComponent, PluginPreviewSectionComponent],
    templateUrl: './plugin-suspend-dialog.component.html',
    styleUrl: './plugin-suspend-dialog.component.scss',
})
export class PluginSuspendDialogComponent implements OnInit {
    protected readonly preview = signal<PluginSuspendPreview | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<string | null>(null);
    protected readonly isSuspending = signal(false);
    protected readonly suspendError = signal<string | null>(null);
    protected readonly view = computed(() => {
        const preview = this.preview();
        return preview ? toPreviewView(preview) : null;
    });
    /** A preview that failed to load does not block the suspension: it must work when something is wrong. */
    protected readonly canSuspend = computed(() => !this.isLoading() && !this.isSuspending());

    protected readonly data = inject<PluginSuspendDialogData>(DIALOG_DATA);
    protected readonly organizationName = this.data.grant.organization.name;
    protected readonly ownedHeading = `What ${this.data.pluginName} owns in ${this.organizationName}`;
    protected readonly organizationFlowsEmptyText = `None. No flow of ${this.organizationName} uses anything ${this.data.pluginName} owns.`;
    protected readonly pluginFlowsHeading = `${this.data.pluginName}'s own flows`;
    protected readonly defaultModelsHeading = `Default-model settings that use ${this.data.pluginName}'s configs`;
    protected readonly titleId = PLUGIN_SUSPEND_DIALOG_TITLE_ID;

    private readonly dialogRef = inject<DialogRef<PluginGrant>>(DialogRef);
    private readonly storage = inject(PluginsAdminStorageService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.loadPreview();
    }

    protected loadPreview(): void {
        this.isLoading.set(true);
        this.loadError.set(null);
        this.storage
            .getSuspendPreview(this.data.identifier, this.data.grant.id)
            .pipe(
                finalize(() => this.isLoading.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (preview) => this.preview.set(preview),
                error: (error: unknown) =>
                    this.loadError.set(toPluginErrorView(error, "Couldn't load what suspending would stop.").message),
            });
    }

    protected suspend(): void {
        if (!this.canSuspend()) return;
        this.isSuspending.set(true);
        this.suspendError.set(null);
        this.storage
            .suspendGrant(this.data.identifier, this.data.grant.id)
            .pipe(
                finalize(() => this.isSuspending.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (grant) => this.dialogRef.close(grant),
                error: (error: unknown) =>
                    this.suspendError.set(toPluginErrorView(error, "Couldn't suspend the plugin.").message),
            });
    }

    protected close(): void {
        if (this.isSuspending()) return;
        this.dialogRef.close();
    }
}

function toPreviewView(preview: PluginSuspendPreview): SuspendPreviewView {
    return {
        owned: {
            items: preview.owned_resources.map((owned) => ({
                key: owned.model,
                name: owned.label,
                detail: String(owned.count),
            })),
            moreCount: 0,
        },
        organizationFlows: toListView(preview.flows.organization, flowItem),
        pluginFlows: toListView(preview.flows.plugin, flowItem),
        sessions: toListView(preview.running_sessions, sessionItem),
        triggers: toListView(preview.triggers, triggerItem),
        realtimeAgents: toListView(preview.realtime_agents, namedItem),
        voiceChannels: toListView(preview.voice_channels, namedItem),
        defaultModels: { items: preview.default_models.map(defaultModelItem), moreCount: 0 },
        defaultModelsHint: defaultModelsHint(preview.default_models),
        dataKeptUntil: preview.data_kept_until,
    };
}

/** The pointer to the settings page only when that page can change one of the settings listed. */
function defaultModelsHint(references: readonly PluginDefaultModelReference[]): string {
    const canRepoint = references.some((reference) =>
        PLUGIN_DEFAULT_MODEL_SETTINGS_ON_SETTINGS_PAGE.has(reference.setting)
    );
    return canRepoint
        ? `${PLUGIN_DEFAULT_MODELS_HINT} ${PLUGIN_DEFAULT_MODELS_REPOINT_HINT}`
        : PLUGIN_DEFAULT_MODELS_HINT;
}

function toListView<Item>(
    list: PluginPreviewList<Item>,
    toItem: (item: Item) => PluginPreviewItemView
): PluginPreviewListView {
    return { items: list.items.map(toItem), moreCount: Math.max(0, list.total - list.items.length) };
}

function flowItem(flow: PluginPreviewFlow): PluginPreviewItemView {
    return { key: String(flow.id), name: flow.name, detail: null };
}

function sessionItem(session: PluginPreviewSession): PluginPreviewItemView {
    const status = PLUGIN_PREVIEW_SESSION_STATUS_LABELS[session.status];
    return {
        key: String(session.id),
        name: session.flow.name,
        detail: `${status} · started ${getRelativeTime(session.created_at)}`,
    };
}

function triggerItem(trigger: PluginPreviewTrigger): PluginPreviewItemView {
    const kind = PLUGIN_PREVIEW_TRIGGER_KIND_LABELS[trigger.kind];
    return {
        key: `${trigger.kind}-${trigger.node_id}`,
        name: trigger.flow.name,
        detail: `${kind}: ${trigger.node_name}`,
    };
}

function namedItem(item: PluginPreviewNamedItem): PluginPreviewItemView {
    return { key: String(item.id), name: item.name, detail: null };
}

function defaultModelItem(reference: PluginDefaultModelReference): PluginPreviewItemView {
    return {
        key: reference.setting,
        name: `${PLUGIN_DEFAULT_MODEL_SETTING_LABELS[reference.setting]} → ${reference.config.name}`,
        detail: null,
    };
}
