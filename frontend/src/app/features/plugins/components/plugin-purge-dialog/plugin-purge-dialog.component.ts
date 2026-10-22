import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { AppSvgIconComponent, ButtonComponent, LoadingSpinnerComponent } from '@shared/components';
import { formatFileSize } from '@shared/utils';
import { filter, finalize, map, Observable } from 'rxjs';

import { PluginDetail, PluginGrant } from '../../models/plugin-admin.model';
import { PluginPreviewListView } from '../../models/plugin-preview-view.model';
import { PluginDataFate, PluginGrantPurgePreview, PluginPurgePreview } from '../../models/plugin-purge-preview.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import {
    defaultModelsListView,
    ownedResourcesListView,
    previewNamedItem,
    previewOrganizationItem,
    previewSessionItem,
    toPreviewListView,
} from '../../utils/plugin-preview-view.util';
import { PluginPreviewSectionComponent } from '../plugin-preview-section/plugin-preview-section.component';

/** The plugin whose data in one organization is to be deleted. */
export interface PluginGrantPurgeTarget {
    identifier: string;
    pluginName: string;
    grant: PluginGrant;
}

/** The plugin to be deleted. */
export interface PluginPurgeTarget {
    identifier: string;
    pluginName: string;
}

/** Delete one grant's data (`grant`), or the whole plugin (`plugin`). */
export type PluginPurgeDialogData =
    | ({ scope: 'grant' } & PluginGrantPurgeTarget)
    | ({ scope: 'plugin' } & PluginPurgeTarget);

/** The grant or the plugin as the server answered once its deletion began. */
export type PluginPurgeDialogResult =
    | { scope: 'grant'; grant: PluginGrant }
    | { scope: 'plugin'; plugin: PluginDetail };

/** The dialog's title element; pass it as `ariaLabelledBy` when opening the dialog. */
export const PLUGIN_PURGE_DIALOG_TITLE_ID = 'plugin-purge-dialog-title';

/** Under the organization's flows that use what a grant's deletion removes. */
export const PLUGIN_PURGE_FLOWS_HINT =
    'They keep working without these parts: agents lose their model, nodes lose their tool or file.';

type LoadedPreview =
    | { scope: 'grant'; preview: PluginGrantPurgePreview }
    | { scope: 'plugin'; preview: PluginPurgePreview };

/** The dialog's fixed texts, which depend only on what is being deleted. */
interface PurgeDialogTexts {
    title: string;
    summary: string;
    ownedHeading: string;
    /** Grant scope only: an empty list of owned resources says so. */
    ownedEmptyText: string | null;
    /** Grant scope only. */
    organizationFlowsEmptyText: string | null;
    pluginFlowsHeading: string;
    organizationsEmptyText: string;
}

/** A grant's preview as the dialog's sections show it. */
interface GrantPurgeView {
    scope: 'grant';
    owned: PluginPreviewListView;
    organizationFlows: PluginPreviewListView;
    organizationFlowsHint: string | null;
    pluginFlows: PluginPreviewListView;
    sessions: PluginPreviewListView;
    defaultModels: PluginPreviewListView;
    /** What becomes of the plugin's own data for the organization; `null` when it has none. */
    pluginDataText: string | null;
}

/** A plugin's preview as the dialog's sections show it. */
interface PluginPurgeView {
    scope: 'plugin';
    organizations: PluginPreviewListView;
    owned: PluginPreviewListView;
    /** `null` when the plugin has no organization removed hook. */
    hookText: string | null;
    removalText: string;
    /** `null` when no data removal is open. */
    openRemovalsText: string | null;
}

/**
 * Deletes a grant's data in its organization, or a whole plugin, after showing what goes. Grant scope: what the plugin
 * owns there, the organization's flows that use it (they keep working without those parts), the plugin's own flows,
 * the running sessions that stop, the default-model settings that are cleared, and what becomes of the plugin's own
 * data. Plugin scope: the organizations, what the plugin owns across them, its organization removed hook, what the
 * node and EpicStaff delete, and the data removals still open.
 *
 * Deleting cannot be undone, so the preview comes first, and the danger button waits for the phrase the server named,
 * typed exactly (nothing is trimmed, case counts); the phrase is sent as typed and checked again by the server. A
 * refusal keeps the dialog open; a phrase that no longer matches (the organization was renamed) also reloads the
 * preview. A click outside does not close it; Escape, Cancel and the close button do, except while the deletion is
 * being asked for.
 */
@Component({
    selector: 'app-plugin-purge-dialog',
    imports: [
        AppSvgIconComponent,
        ButtonComponent,
        LoadingSpinnerComponent,
        PluginPreviewSectionComponent,
        ReactiveFormsModule,
    ],
    templateUrl: './plugin-purge-dialog.component.html',
    styleUrl: './plugin-purge-dialog.component.scss',
})
export class PluginPurgeDialogComponent implements OnInit {
    protected readonly loaded = signal<LoadedPreview | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<string | null>(null);
    protected readonly isPurging = signal(false);
    protected readonly purgeError = signal<string | null>(null);
    protected readonly view = computed<GrantPurgeView | PluginPurgeView | null>(() => {
        const loaded = this.loaded();
        if (!loaded) return null;
        return loaded.scope === 'grant'
            ? toGrantView(loaded.preview, this.data.pluginName)
            : toPluginView(loaded.preview, this.data.pluginName);
    });
    /** The phrase the server asks for; `null` until its preview is loaded, so nothing can be confirmed before. */
    protected readonly verificationPhrase = computed(() => this.loaded()?.preview.verification_phrase ?? null);
    /** Only the exact phrase, as typed: nothing is trimmed and case counts. */
    protected readonly canPurge = computed(() => {
        const phrase = this.verificationPhrase();
        return phrase !== null && this.typedPhrase() === phrase && !this.isLoading() && !this.isPurging();
    });

    /** In grant scope, named after the organization as the preview has it once loaded: it may have been renamed. */
    protected readonly texts = computed(() => {
        const loaded = this.loaded();
        return dialogTexts(this.data, loaded?.scope === 'grant' ? loaded.preview.organization.name : null);
    });

    protected readonly phraseControl = new FormControl('', { nonNullable: true });
    protected readonly data = inject<PluginPurgeDialogData>(DIALOG_DATA);
    protected readonly titleId = PLUGIN_PURGE_DIALOG_TITLE_ID;

    private readonly typedPhrase = toSignal(this.phraseControl.valueChanges, { initialValue: '' });
    private readonly dialogRef = inject<DialogRef<PluginPurgeDialogResult>>(DialogRef);
    private readonly storage = inject(PluginsAdminStorageService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.dialogRef.keydownEvents
            .pipe(
                filter((event) => event.key === 'Escape'),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.close());
        this.loadPreview();
    }

    protected loadPreview(): void {
        this.isLoading.set(true);
        this.loadError.set(null);
        this.previewRequest()
            .pipe(
                finalize(() => this.isLoading.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (loaded) => this.loaded.set(loaded),
                error: (error: unknown) => {
                    this.loaded.set(null);
                    this.loadError.set(toPluginErrorView(error, "Couldn't load what deleting would remove.").message);
                },
            });
    }

    protected purge(): void {
        if (!this.canPurge()) return;
        this.isPurging.set(true);
        this.purgeError.set(null);
        this.purgeRequest(this.typedPhrase())
            .pipe(
                finalize(() => this.isPurging.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (result) => this.dialogRef.close(result),
                error: (error: unknown) => {
                    const failure = toPluginErrorView(error, "Couldn't start the deletion.");
                    this.purgeError.set(failure.message);
                    // The phrase names the organization, which may have been renamed since the preview loaded.
                    if (failure.code === 'invalid_purge_phrase') this.loadPreview();
                },
            });
    }

    protected close(): void {
        if (this.isPurging()) return;
        this.dialogRef.close();
    }

    private previewRequest(): Observable<LoadedPreview> {
        const data = this.data;
        if (data.scope === 'grant') {
            return this.storage
                .getGrantPurgePreview(data.identifier, data.grant.id)
                .pipe(map((preview): LoadedPreview => ({ scope: 'grant', preview })));
        }
        return this.storage
            .getPluginPurgePreview(data.identifier)
            .pipe(map((preview): LoadedPreview => ({ scope: 'plugin', preview })));
    }

    private purgeRequest(phrase: string): Observable<PluginPurgeDialogResult> {
        const data = this.data;
        if (data.scope === 'grant') {
            return this.storage
                .purgeGrant(data.identifier, data.grant.id, phrase)
                .pipe(map((grant): PluginPurgeDialogResult => ({ scope: 'grant', grant })));
        }
        return this.storage
            .purgePlugin(data.identifier, phrase)
            .pipe(map((plugin): PluginPurgeDialogResult => ({ scope: 'plugin', plugin })));
    }
}

function dialogTexts(data: PluginPurgeDialogData, loadedOrganizationName: string | null): PurgeDialogTexts {
    const pluginName = data.pluginName;
    const shared = {
        pluginFlowsHeading: `${pluginName}'s own flows`,
        organizationsEmptyText: `None. ${pluginName} is not granted to any organization.`,
    };
    if (data.scope === 'grant') {
        const organizationName = loadedOrganizationName ?? data.grant.organization.name;
        return {
            ...shared,
            title: `Delete ${pluginName}'s data in ${organizationName} now`,
            summary: `Everything ${pluginName} owns in ${organizationName} is deleted, and nothing goes to the recycle bin.`,
            ownedHeading: `What ${pluginName} owns in ${organizationName}`,
            ownedEmptyText: `Nothing. ${pluginName} owns nothing in ${organizationName}.`,
            organizationFlowsEmptyText: `None. No flow of ${organizationName} uses anything ${pluginName} owns.`,
        };
    }
    return {
        ...shared,
        title: `Delete ${pluginName} permanently`,
        summary: `${pluginName} is deleted from every organization, with everything it owns. Nothing goes to the recycle bin.`,
        ownedHeading: `What ${pluginName} owns in all organizations`,
        ownedEmptyText: null,
        organizationFlowsEmptyText: null,
    };
}

function toGrantView(preview: PluginGrantPurgePreview, pluginName: string): GrantPurgeView {
    const organizationFlows = toPreviewListView(preview.flows.organization, previewNamedItem);
    return {
        scope: 'grant',
        owned: ownedResourcesListView(preview.owned_resources),
        organizationFlows,
        organizationFlowsHint: organizationFlows.items.length > 0 ? PLUGIN_PURGE_FLOWS_HINT : null,
        pluginFlows: toPreviewListView(preview.flows.plugin, previewNamedItem),
        sessions: toPreviewListView(preview.running_sessions, previewSessionItem),
        defaultModels: defaultModelsListView(preview.default_models),
        pluginDataText: pluginDataText(preview.plugin_data, pluginName, preview.organization.name),
    };
}

function toPluginView(preview: PluginPurgePreview, pluginName: string): PluginPurgeView {
    return {
        scope: 'plugin',
        organizations: toPreviewListView(preview.organizations, previewOrganizationItem),
        owned: ownedResourcesListView(preview.owned_resources),
        hookText: preview.has_org_removed_hook
            ? `${pluginName} first deletes its own data for each organization.`
            : null,
        removalText: removalText(preview),
        openRemovalsText: openRemovalsText(preview.data_removals_open),
    };
}

function pluginDataText(fate: PluginDataFate, pluginName: string, organizationName: string): string | null {
    switch (fate) {
        case 'deleted_by_plugin':
            return `${pluginName} deletes its own data for ${organizationName}.`;
        case 'kept_until_plugin_deleted':
            return `${pluginName}'s own data for ${organizationName} stays until ${pluginName} is deleted.`;
        case 'none':
            return null;
    }
}

/**
 * What the node and EpicStaff delete of the plugin, without the parts it does not have: the node part only for a
 * plugin with a backend, its database only when it has one, its size only when known, its frontend only when it has
 * one.
 */
function removalText(preview: PluginPurgePreview): string {
    const epicStaffPart = preview.has_spa
        ? 'EpicStaff deletes its frontend and package files'
        : 'EpicStaff deletes its package files';
    const nodePart = preview.has_backend ? nodeRemovalText(preview.database) : null;
    const steps = nodePart ? `${nodePart}, and ${epicStaffPart}` : epicStaffPart;
    return `Then ${steps}. No backup is taken.`;
}

function nodeRemovalText(database: PluginPurgePreview['database']): string {
    if (!database) return 'the plugin node deletes its files';
    const size = database.size_bytes === null ? '' : ` (${formatFileSize(database.size_bytes, 'auto')})`;
    return `the plugin node deletes its database ${database.name}${size} and its files`;
}

function openRemovalsText(count: number): string | null {
    if (count <= 0) return null;
    return count === 1 ? '1 data removal is still waiting.' : `${count} data removals are still waiting.`;
}
