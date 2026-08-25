import { Dialog } from '@angular/cdk/dialog';
import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    model,
    output,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    CheckboxComponent,
    ConfirmationDialogService,
    SelectDropdownComponent,
    SelectDropdownHeaderAction,
    SelectDropdownListItem,
    SelectDropdownTab,
    SelectDropdownTriggerDirective,
} from '@shared/components';
import { DragHoverDirective, EnterBlurDirective, TooltipOnOverflowDirective } from '@shared/directives';
import { map, switchMap, take } from 'rxjs/operators';

import { ToastService } from '../../../../../../../../services/notifications/toast.service';
import { CreateCustomToolDialogComponent } from '../../../../../../../../user-settings-page/tools/custom-tool-editor/create-custom-tool-dialog/create-custom-tool-dialog.component';
import {
    CreateFolderDialogComponent,
    CreateFolderDialogResult,
} from '../../../../../../../files/components/create-folder-dialog/create-folder-dialog.component';
import { StorageItem } from '../../../../../../../files/models/storage.models';
import { StorageApiService } from '../../../../../../../files/services/storage-api.service';
import { StorageDragService } from '../../../../../../../files/services/storage-drag.service';
import { CreateCollectionDialogComponent } from '../../../../../../../knowledge-sources/components/create-collection-dialog/create-collection-dialog.component';
import { CollectionsStorageService } from '../../../../../../../knowledge-sources/services/collections-storage.service';
import { McpToolDialogComponent } from '../../../../../../../tools/components/mcp-tool-dialog/mcp-tool-dialog.component';
import { GetMcpToolRequest } from '../../../../../../../tools/models/mcp-tool.model';
import { GetPythonCodeToolRequest } from '../../../../../../../tools/models/python-code-tool.model';
import { AgentSurfacePlace } from '../../../../../../models/agent-definition.model';
import {
    CreateSurfaceRequest,
    PartialUpdateSurfaceRequest,
    PermTriState,
    Surface,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfacePythonTool,
    SurfaceSaveError,
    SurfaceStorageItem,
} from '../../../../../../models/surface.model';
import {
    nextPermState,
    SURFACE_FILE_PERM_COLUMNS,
    SurfaceCollectionOption,
    SurfaceFileDisplayRow,
    SurfaceFilePerms,
    SurfaceFileRow,
    SurfaceTabId,
    SurfaceToolOption,
} from '../../../../../../models/surface-card.model';
import { categoryToPlace, SurfaceCategoryId } from '../../../../../../models/surface-category.model';
import { StorageFileMeta, SurfaceCatalogsStore } from '../../../../../../services/surface-catalogs-store.service';
import { DELETE_CONFIRM_DIALOG_WIDTH } from '../../../../../../utils/delete-confirmation.util';
import {
    buildClearSurfaceBundleDialog,
    SurfaceBundleClearKind,
} from '../../../../../../utils/surface-bundle-confirmation.util';
import { buildSurfaceFileDisplayRows, buildSurfaceFileStats } from '../../../../../../utils/surface-file-tree.util';
import { SurfaceKnowledgeAdvancedComponent } from './surface-knowledge-advanced/surface-knowledge-advanced.component';

@Component({
    selector: 'app-surface-card',
    imports: [
        CommonModule,
        FormsModule,
        AppSvgIconComponent,
        MatTooltipModule,
        SelectDropdownComponent,
        SelectDropdownTriggerDirective,
        EnterBlurDirective,
        DragHoverDirective,
        TooltipOnOverflowDirective,
        SurfaceKnowledgeAdvancedComponent,
        CheckboxComponent,
        OverlayModule,
    ],
    templateUrl: './surface-card.component.html',
    styleUrls: ['./surface-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SurfaceCardComponent {
    private readonly catalogs: SurfaceCatalogsStore = inject(SurfaceCatalogsStore);
    private readonly storageApi: StorageApiService = inject(StorageApiService);
    private readonly storageDrag = inject(StorageDragService);
    private readonly toast = inject(ToastService);
    private readonly collectionsStorage: CollectionsStorageService = inject(CollectionsStorageService);
    private readonly destroyRef: DestroyRef = inject(DestroyRef);
    private readonly dialog: Dialog = inject(Dialog);
    private readonly confirm: ConfirmationDialogService = inject(ConfirmationDialogService);

    surface = input<Surface | null>(null);
    readOnly = input<boolean>(false);
    showMeta = input<boolean>(false);
    /** The owning AgentDefinition's llm_config — forwarded to the knowledge-advanced
     * panel's RAG tab so suggested-params requests know which LLM's context window to use. */
    llmConfigId = input<number | null>(null);

    expanded = model<boolean>(false);
    isShared = input<boolean>(false);
    currentPlace = input<SurfaceCategoryId | null>(null);
    draggable = input<boolean>(false);
    hideHeader = input<boolean>(false);
    isCreating = input<boolean>(false);
    hideInstructions = input<boolean>(false);
    hideDescriptions = input<boolean>(false);
    flat = input<boolean>(false);
    // Full place-set this surface holds under the agent (for the place checkboxes).
    surfacePlaces = input<AgentSurfacePlace[]>([]);
    // True while a placement PATCH is in flight — disables the checkboxes and holds
    // the optimistic local state until the store settles (see the resync effect).
    placesBusy = input<boolean>(false);
    /** Last surface-save failure from the store; only reverts this card when surfaceId matches. */
    saveError = input<SurfaceSaveError | null>(null);

    readonly save = output<void>();
    readonly cancel = output<void>();
    readonly surfaceChange = output<PartialUpdateSurfaceRequest>();
    readonly renameSurface = output<string>();
    readonly createDraft = output<CreateSurfaceRequest>();
    readonly openSource = output<void>();
    readonly detach = output<void>();
    readonly makeShared = output<void>();
    readonly makeAgentSpecificCopy = output<void>();
    readonly placesChange = output<AgentSurfacePlace[]>();
    readonly duplicate = output<void>();
    readonly deleteSurface = output<void>();
    readonly draftContentChanged = output<void>();

    readonly activeTab = signal<SurfaceTabId>('tools');
    readonly instructions = signal<string>('');
    private readonly instructionsFocused = signal<boolean>(false);
    private lastSentInstructions: string | null = null;

    readonly menuOpen = signal<boolean>(false);
    private readonly instructionsTextarea = viewChild<ElementRef<HTMLTextAreaElement>>('instrTa');

    readonly name = signal<string>('');
    private readonly nameFocused = signal<boolean>(false);
    private lastSentName: string | null = null;

    // Optimistic local copy of the surface's place-set. Seeded/resynced from the
    // `surfacePlaces` input whenever no placement PATCH is in flight, so it holds the
    // optimistic value during a save and reverts to store state if the PATCH fails.
    private readonly localPlaces = signal<AgentSurfacePlace[]>([]);

    readonly everywhereChecked = computed(() => this.localPlaces().includes('all'));
    readonly flowChecked = computed(() => this.everywhereChecked() || this.localPlaces().includes('flow'));
    readonly chatChecked = computed(() => this.everywhereChecked() || this.localPlaces().includes('chat'));
    readonly realtimeChecked = computed(() => this.everywhereChecked() || this.localPlaces().includes('realtime'));

    readonly showAgentSpecificMenu = computed(() => !this.isShared() && !this.readOnly());
    readonly showSharedInAgentMenu = computed(() => this.isShared() && this.readOnly());
    readonly showSharedSurfacesMenu = computed(() => this.isShared() && !this.readOnly() && this.showMeta());
    readonly hasMenuItems = computed(
        () => this.showAgentSpecificMenu() || this.showSharedInAgentMenu() || this.showSharedSurfacesMenu()
    );
    readonly showDelete = computed(() => !this.showSharedInAgentMenu());

    toggleExpand(): void {
        this.menuOpen.set(false);
        this.expanded.update((v) => !v);
    }

    onNameInput(value: string): void {
        this.name.set(value);
    }

    onNameFocus(): void {
        this.nameFocused.set(true);
    }

    commitRename(): void {
        this.nameFocused.set(false);
        const name = this.name().trim();
        const current = this.surface()?.name ?? '';
        if (this.isCreating()) {
            if (!name || name === current) return;
            this.createDraft.emit(this.buildCreateRequest(name));
            return;
        }
        this.lastSentName = name;
        if (!name || name === current) return;
        this.renameSurface.emit(name);
    }

    buildCreateRequest(name: string): CreateSurfaceRequest {
        const { python_tools, mcp_tools } = this.buildToolsPayload();
        return {
            name: name.trim(),
            description: '',
            instructions: this.instructions(),
            python_tools,
            mcp_tools,
            storage_items: this.buildStoragePayload(),
            knowledge: this.buildKnowledgePayload(),
        };
    }

    private hasDraftContent(): boolean {
        const { python_tools, mcp_tools } = this.buildToolsPayload();
        return (
            python_tools.length > 0 ||
            mcp_tools.length > 0 ||
            this.buildStoragePayload().length > 0 ||
            this.buildKnowledgePayload().length > 0 ||
            this.instructions().trim().length > 0
        );
    }

    private notifyDraftContent(): void {
        if (this.isCreating() && this.hasDraftContent()) this.draftContentChanged.emit();
    }

    toggleMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.menuOpen.update((v) => !v);
    }

    closeMenu(): void {
        this.menuOpen.set(false);
    }

    onHeaderAction(
        action: 'openSource' | 'detach' | 'makeShared' | 'makeCopy' | 'duplicate' | 'delete',
        event: MouseEvent
    ): void {
        event.stopPropagation();
        this.menuOpen.set(false);
        switch (action) {
            case 'openSource':
                this.openSource.emit();
                break;
            case 'detach':
                this.detach.emit();
                break;
            case 'makeShared':
                this.makeShared.emit();
                break;
            case 'makeCopy':
                this.makeAgentSpecificCopy.emit();
                break;
            case 'duplicate':
                this.duplicate.emit();
                break;
            case 'delete':
                this.deleteSurface.emit();
                break;
        }
    }

    // The kebab is kept open by a stopPropagation wrapper around the checkbox group,
    // so these only need the new checked state.
    onToggleEverywhere(checked: boolean): void {
        if (this.placesBusy()) return;
        const next: AgentSurfacePlace[] = checked ? ['all'] : ['flow', 'chat', 'realtime'];
        this.applyPlaces(next);
    }

    onTogglePlace(place: Exclude<AgentSurfacePlace, 'all'>, checked: boolean): void {
        if (this.placesBusy() || this.everywhereChecked()) return;
        const current = this.localPlaces().filter((p) => p !== 'all');
        let next: AgentSurfacePlace[];
        if (checked) {
            next = current.includes(place) ? current : [...current, place];
        } else {
            next = current.filter((p) => p !== place);
            if (next.length === 0) return; // keep at least one place; use Detach to remove entirely
        }
        this.applyPlaces(next);
    }

    private applyPlaces(next: AgentSurfacePlace[]): void {
        this.localPlaces.set(next);
        this.placesChange.emit(next);
    }

    // The X on a card detaches the surface from THIS place only; if it was the last place,
    // the surface is removed from the agent entirely.
    onDetachPlace(event: MouseEvent): void {
        event.stopPropagation();
        this.menuOpen.set(false);
        if (this.placesBusy()) return;
        const cat = this.currentPlace();
        const thisPlace = cat ? categoryToPlace(cat) : null;
        const next = thisPlace ? this.localPlaces().filter((p) => p !== thisPlace) : [];
        if (next.length === 0) {
            this.detach.emit();
        } else {
            this.applyPlaces(next);
        }
    }

    // Prefer opening below the trigger (right-aligned); flip above when there isn't room.
    readonly menuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
    ];

    readonly toolsExpanded = signal<boolean>(false);
    readonly filesExpanded = signal<boolean>(false);
    readonly collectionsExpanded = signal<boolean>(false);

    readonly toolOptions = computed<SurfaceToolOption[]>(() => [
        ...this.catalogs.pythonTools(),
        ...this.catalogs.mcpTools(),
    ]);
    readonly selectedToolKeys = signal<Set<string>>(new Set());
    private lastSentToolKeys: string | null = null;

    readonly toolItems = computed<SelectDropdownListItem<string>[]>(() =>
        this.toolOptions().map((t) => ({ name: t.name, value: this.toolKey(t) }))
    );
    readonly selectedToolValues = computed<string[]>(() => [...this.selectedToolKeys()]);
    readonly selectedTools = computed<SurfaceToolOption[]>(() =>
        this.toolOptions().filter((t) => this.selectedToolKeys().has(this.toolKey(t)))
    );

    toolKey(t: SurfaceToolOption): string {
        return `${t.kind}:${t.id}`;
    }

    readonly toolSubtab = signal<'custom' | 'mcp'>('custom');
    readonly toolTabs: SelectDropdownTab[] = [
        { id: 'custom', label: 'Custom Tools' },
        { id: 'mcp', label: 'MCP Tools' },
    ];
    readonly toolHeaderAction = computed<SelectDropdownHeaderAction>(() => ({
        icon: 'plus',
        label: this.toolSubtab() === 'custom' ? 'Create custom tool' : 'Add MCP tool',
    }));

    private readonly pendingToolKeys = signal<Set<string> | null>(null);
    private readonly effectiveToolKeys = computed(() => this.pendingToolKeys() ?? this.selectedToolKeys());

    private toolItemsOfKind(kind: 'python' | 'mcp'): SelectDropdownListItem<number>[] {
        return this.toolOptions()
            .filter((t) => t.kind === kind)
            .map((t) => ({ name: t.name, value: t.id }));
    }

    private idsOfKind(keys: Set<string>, kind: 'python' | 'mcp'): number[] {
        const prefix = `${kind}:`;
        return [...keys].filter((k) => k.startsWith(prefix)).map((k) => Number(k.split(':')[1]));
    }

    readonly activeToolItems = computed<SelectDropdownListItem<number>[]>(() =>
        this.toolItemsOfKind(this.toolSubtab() === 'custom' ? 'python' : 'mcp')
    );
    readonly activeToolIds = computed<number[]>(() =>
        this.idsOfKind(this.effectiveToolKeys(), this.toolSubtab() === 'custom' ? 'python' : 'mcp')
    );

    onToolTabChange(id: string): void {
        this.toolSubtab.set(id === 'mcp' ? 'mcp' : 'custom');
    }

    onToolsOpenedChange(opened: boolean): void {
        this.toolsExpanded.set(opened);
        if (opened) {
            this.pendingToolKeys.set(new Set(this.selectedToolKeys()));
        } else {
            this.pendingToolKeys.set(null);
        }
    }

    private withKindMerged(base: Set<string>, values: unknown[]): Set<string> {
        const kind: 'python' | 'mcp' = this.toolSubtab() === 'custom' ? 'python' : 'mcp';
        const ids = values as number[];
        const others = [...base].filter((k) => !k.startsWith(`${kind}:`));
        return new Set([...others, ...ids.map((id) => `${kind}:${id}`)]);
    }

    onActiveToolsDraftChange(values: unknown[]): void {
        if (this.readOnly()) return;
        this.pendingToolKeys.set(this.withKindMerged(this.effectiveToolKeys(), values));
    }

    onActiveToolsChange(values: unknown[]): void {
        if (this.readOnly()) return;
        const merged = this.withKindMerged(this.effectiveToolKeys(), values);
        this.pendingToolKeys.set(null);
        this.selectedToolKeys.set(merged);
        this.emitToolsChange();
    }

    readonly fileRows = signal<SurfaceFileRow[]>([]);
    private lastSentStorageItems: string | null = null;
    readonly collapsedFolderPaths = signal<Set<string>>(new Set());
    readonly permColumns = SURFACE_FILE_PERM_COLUMNS;

    readonly fileDropdownNodes = this.catalogs.storageTree;
    private readonly fileMetaById = new Map<number, StorageFileMeta>();
    private readonly requestedFileMetaIds = new Set<number>();

    /** Shared tree cache first, then this card's filesByIds backfill. */
    private metaFor(id: number): StorageFileMeta | undefined {
        return this.catalogs.storageFileMeta().get(id) ?? this.fileMetaById.get(id);
    }

    readonly filesHeaderAction: SelectDropdownHeaderAction = { icon: 'plus', label: 'Add files to storage' };

    readonly visiblePermColumns = computed(() => {
        if (!this.readOnly()) return SURFACE_FILE_PERM_COLUMNS;
        const used = new Set<keyof SurfaceFilePerms>();
        for (const row of this.fileRows()) {
            for (const col of SURFACE_FILE_PERM_COLUMNS) {
                if (row.perms[col.key] !== 'unset') used.add(col.key);
            }
        }
        return SURFACE_FILE_PERM_COLUMNS.filter((c) => used.has(c.key));
    });

    readonly selectedFileIds = computed<number[]>(() =>
        this.fileRows()
            .filter((r) => r.type === 'file')
            .map((r) => r.id)
    );
    // Folder rows resolved back to their dropdown ids (path strings) so the tree pre-checks them.
    readonly selectedFolderPaths = computed<string[]>(() =>
        this.fileRows()
            .filter((r) => r.type === 'folder')
            .map((r) => r.path.replace(/\/+$/, ''))
    );

    readonly fileStats = computed(() => buildSurfaceFileStats(this.fileRows()));

    readonly displayFileRows = computed(() =>
        buildSurfaceFileDisplayRows(this.fileRows(), this.collapsedFolderPaths())
    );

    readonly collectionOptions = this.catalogs.collections;
    readonly knowledgeItems = signal<SurfaceKnowledge[]>([]);
    private lastSentKnowledge: string | null = null;
    readonly selectedCollectionIds = computed<ReadonlySet<number>>(
        () => new Set(this.knowledgeItems().map((k) => k.collection))
    );
    // A collection with no RAG picked yet (none of the three configs set). The backend rejects
    // such rows, so they're kept in the UI but excluded from the saved payload until a RAG is set.
    readonly collectionsWithoutRag = computed<ReadonlySet<number>>(
        () =>
            new Set(
                this.knowledgeItems()
                    .filter((k) => !this.hasRag(k))
                    .map((k) => k.collection)
            )
    );
    readonly collectionAdvancedOpen = signal<boolean>(false);

    readonly collectionHeaderAction: SelectDropdownHeaderAction = { icon: 'plus', label: 'Add new collection' };

    readonly collectionItems = computed<SelectDropdownListItem<number>[]>(() =>
        this.collectionOptions().map((c) => ({ name: c.name, value: c.id }))
    );
    readonly selectedCollectionValues = computed<number[]>(() => [...this.selectedCollectionIds()]);
    readonly selectedCollections = computed<SurfaceCollectionOption[]>(() =>
        this.collectionOptions().filter((c) => this.selectedCollectionIds().has(c.id))
    );

    private lastSurfaceId: number | null | undefined = undefined;
    private lastSaveErrorTick: number | null = null;

    constructor() {
        // Resync the optimistic place-set from the input whenever no placement PATCH is
        // in flight. On save success the input carries the new value; on failure it still
        // carries the pre-edit value, so this reverts the optimistic toggle. While busy we
        // keep the optimistic value (the store `saving` flips synchronously on emit).
        effect(() => {
            const busy = this.placesBusy();
            const input = this.surfacePlaces();
            if (busy) return;
            untracked(() => this.localPlaces.set([...input]));
        });

        effect(() => {
            const s = this.surface();
            const error = this.saveError();

            // A failed save for THIS surface invalidates the snapshots: the optimistic local
            // value was rejected, the store re-synced the server surface, but the snapshot still
            // holds the rejected value — so the guards below would refuse the server's (correct)
            // value and leave the invalid tool/file/collection on screen. Clearing the snapshots
            // lets the server value win. Errors for other surfaces are ignored (per-id).
            const errorForThis = error && s && error.surfaceId === s.id ? error.tick : null;

            // Switching to a different surface (or into/out of create mode) makes the "last sent"
            // snapshots meaningless — they described a different object; reset unconditionally.
            if (s?.id !== this.lastSurfaceId) {
                this.lastSurfaceId = s?.id ?? null;
                this.lastSaveErrorTick = errorForThis;
                this.clearSentSnapshots();
            } else if (errorForThis != null && errorForThis !== this.lastSaveErrorTick) {
                // Only a NEW failure of this surface clears the snapshots. Guarding on
                // "!= null && changed" (not just "changed") stops another surface's error —
                // which drives errorForThis back to null here — from spuriously reverting an
                // in-flight edit on this card.
                this.lastSaveErrorTick = errorForThis;
                this.clearSentSnapshots();
            }

            // Autosave PATCHes one field at a time but the backend always returns the
            // full surface, so every autosave round-trip re-fires this effect for ALL
            // fields. Only accept the server's value for a field once it matches what
            // this card last sent (or nothing has been sent yet) — otherwise the field
            // is either actively being edited (name/instructions, gated on focus) or
            // has a newer local change in flight (tools/files/knowledge), and
            // overwriting it here would wipe unsaved input out from under the user.
            if (!this.nameFocused()) {
                const incomingName = s?.name ?? '';
                if (this.lastSentName == null || this.lastSentName === incomingName) {
                    this.name.set(incomingName);
                }
            }

            if (!this.instructionsFocused()) {
                const incoming = s?.instructions ?? '';
                if (this.lastSentInstructions == null || this.lastSentInstructions === incoming) {
                    this.instructions.set(incoming);
                }
            }

            const toolKeys = new Set<string>([
                ...(s?.python_tools ?? []).map((t) => `python:${t.python_tool}`),
                ...(s?.mcp_tools ?? []).map((t) => `mcp:${t.mcp_tool}`),
            ]);
            if (this.lastSentToolKeys == null || this.lastSentToolKeys === serializeToolKeys(toolKeys)) {
                this.selectedToolKeys.set(toolKeys);
            }

            const knowledge = s?.knowledge ?? [];
            if (this.lastSentKnowledge == null || this.lastSentKnowledge === serializeKnowledge(knowledge)) {
                // The server only stores RAG-configured collections, so re-attach any locally
                // added-but-not-yet-configured (RAG-less) ones that aren't in the server list —
                // otherwise a save of some other field would silently drop them from the UI.
                const serverIds = new Set(knowledge.map((k) => k.collection));
                const pendingRagless = untracked(() =>
                    this.knowledgeItems().filter((k) => !this.hasRag(k) && !serverIds.has(k.collection))
                );
                this.knowledgeItems.set([...knowledge, ...pendingRagless]);
            }

            const storageItems = s?.storage_items ?? [];
            if (
                this.lastSentStorageItems == null ||
                this.lastSentStorageItems === serializeStorageItems(storageItems)
            ) {
                this.fileRows.set(
                    storageItems.map((si) => {
                        const meta = untracked(() => this.metaFor(si.storage_file));
                        return {
                            id: si.storage_file,
                            type: meta?.type ?? 'file',
                            name: meta?.name ?? `File #${si.storage_file}`,
                            path: meta?.path ?? '',
                            perms: {
                                list: si.can_list,
                                view: si.can_view,
                                edit: si.can_edit,
                                delete: si.can_delete,
                            },
                        };
                    })
                );
            }
        });

        effect(() => {
            if (!this.expanded()) return;
            this.loadCatalogs();
        });

        // While a storage item is being dragged, any visible editable card lands on the
        // Files tab so the drop result is immediately in view.
        effect(() => {
            if (!this.storageDrag.isDragging()) return;
            if (this.readOnly()) return;
            if (!this.expanded() && !this.hideHeader()) return;
            this.activeTab.set('files');
        });

        effect(() => {
            if (!this.expanded() && !this.hideHeader()) return;
            const missing = this.fileRows()
                .map((r) => r.id)
                .filter((id) => this.metaFor(id) == null && !this.requestedFileMetaIds.has(id));
            if (!missing.length) return;
            missing.forEach((id) => this.requestedFileMetaIds.add(id));
            this.storageApi
                .filesByIds(missing)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (files) => {
                        for (const f of files)
                            this.fileMetaById.set(f.id, { name: f.name, path: f.path, type: f.item_type });
                        this.refreshFileRowNames();
                    },
                    error: () => missing.forEach((id) => this.requestedFileMetaIds.delete(id)),
                });
        });

        effect(() => {
            this.instructions();
            const ta = this.instructionsTextarea()?.nativeElement;
            if (!ta) return;
            this.adjustInstructionsHeight(ta);
            // Re-measure after layout settles (first show / font load), otherwise
            // scrollHeight can read the minimal rows height before reflow.
            requestAnimationFrame(() => this.adjustInstructionsHeight(ta));
        });
    }

    private catalogsRequested = false;

    private loadCatalogs(): void {
        if (this.catalogsRequested) return;
        this.catalogsRequested = true;
        this.catalogs.loadPythonTools().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.catalogs.loadMcpTools().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.catalogs.loadCollections().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.refreshStorageRoot();
    }

    private refreshStorageRoot(): void {
        this.catalogs
            .loadStorageTree()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.refreshFileRowNames());
    }

    private reloadStorageRoot(): void {
        this.catalogs
            .reloadStorageTree()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.refreshFileRowNames());
    }

    private refreshFileRowNames(): void {
        this.fileRows.update((rows) =>
            rows.map((r) => {
                const meta = this.metaFor(r.id);
                return meta ? { ...r, name: meta.name, path: meta.path, type: meta.type } : r;
            })
        );
    }

    selectTab(tab: SurfaceTabId): void {
        this.activeTab.set(tab);
    }

    adjustInstructionsHeight(textarea: HTMLTextAreaElement): void {
        const maxPx = 300;
        textarea.style.height = 'auto';
        const full = textarea.scrollHeight;
        textarea.style.height = `${Math.min(full, maxPx)}px`;
        textarea.style.overflowY = full > maxPx ? 'auto' : 'hidden';
    }

    onInstructionsFocus(): void {
        this.instructionsFocused.set(true);
    }

    onInstructionsBlur(): void {
        this.instructionsFocused.set(false);
        if (this.isCreating()) {
            this.notifyDraftContent();
            return;
        }
        const value = this.instructions();
        this.lastSentInstructions = value;
        if (value === (this.surface()?.instructions ?? '')) return;
        this.surfaceChange.emit({ instructions: value });
    }

    onToolsChange(values: unknown[]): void {
        if (this.readOnly()) return;
        this.selectedToolKeys.set(new Set(values as string[]));
        this.emitToolsChange();
    }

    removeTool(key: string, event: MouseEvent): void {
        if (this.readOnly()) return;
        event.stopPropagation();
        this.selectedToolKeys.update((set) => {
            const next = new Set(set);
            next.delete(key);
            return next;
        });
        this.emitToolsChange();
    }

    private confirmClearBundle(kind: SurfaceBundleClearKind, size: number, apply: () => void): void {
        if (this.readOnly() || size === 0) return;
        this.confirm
            .confirm(buildClearSurfaceBundleDialog(kind, this.surface()?.name), { width: DELETE_CONFIRM_DIALOG_WIDTH })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) apply();
            });
    }

    clearTools(event: MouseEvent): void {
        event.stopPropagation();
        this.confirmClearBundle('tools', this.selectedToolKeys().size, () => {
            this.selectedToolKeys.set(new Set());
            this.emitToolsChange();
        });
    }

    private buildToolsPayload(): { python_tools: SurfacePythonTool[]; mcp_tools: SurfaceMcpTool[] } {
        const python_tools: SurfacePythonTool[] = [];
        const mcp_tools: SurfaceMcpTool[] = [];
        for (const key of this.selectedToolKeys()) {
            const [kind, idStr] = key.split(':');
            const id = Number(idStr);
            if (kind === 'python') python_tools.push({ python_tool: id, mode: 'allow' });
            else if (kind === 'mcp') mcp_tools.push({ mcp_tool: id, mode: 'allow' });
        }
        return { python_tools, mcp_tools };
    }

    private emitToolsChange(): void {
        this.lastSentToolKeys = serializeToolKeys(this.selectedToolKeys());
        if (this.isCreating()) {
            this.notifyDraftContent();
            return;
        }
        this.surfaceChange.emit(this.buildToolsPayload());
    }

    openCreateTool(): void {
        if (this.readOnly()) return;
        if (this.toolSubtab() === 'custom') {
            this.dialog
                .open<GetPythonCodeToolRequest>(CreateCustomToolDialogComponent)
                .closed.pipe(take(1))
                .subscribe((tool) => {
                    if (tool)
                        this.addCreatedTool({
                            id: tool.id,
                            name: tool.name,
                            description: tool.description ?? '',
                            kind: 'python',
                        });
                });
        } else {
            this.dialog
                .open<GetMcpToolRequest>(McpToolDialogComponent, { data: {} })
                .closed.pipe(take(1))
                .subscribe((tool) => {
                    if (tool) this.addCreatedTool({ id: tool.id, name: tool.name, description: '', kind: 'mcp' });
                });
        }
    }

    private addCreatedTool(tool: SurfaceToolOption): void {
        this.catalogs.addTool(tool);
        this.selectedToolKeys.update((set) => new Set([...set, this.toolKey(tool)]));
        this.emitToolsChange();
    }

    onFilesSelectionChange(detail: { fileIds: unknown[]; folderIds: (string | number)[] }): void {
        if (this.readOnly()) return;
        const byId = new Map(this.fileRows().map((r) => [r.id, r]));
        const next: SurfaceFileRow[] = [];

        for (const raw of detail.fileIds) {
            if (typeof raw !== 'number') continue;
            next.push(byId.get(raw) ?? this.newFileRow(raw, 'file'));
        }
        // Folder dropdown ids are path strings; resolve each to its numeric StorageFile id.
        for (const raw of detail.folderIds) {
            const id = typeof raw === 'number' ? raw : this.catalogs.folderIdForPath(String(raw));
            if (id == null) continue;
            next.push(byId.get(id) ?? this.newFileRow(id, 'folder'));
        }

        this.fileRows.set(next);
        this.emitStorageChange();
    }

    private newFileRow(id: number, type: 'file' | 'folder'): SurfaceFileRow {
        const meta = this.metaFor(id);
        return {
            id,
            type: meta?.type ?? type,
            name: meta?.name ?? `File #${id}`,
            path: meta?.path ?? '',
            perms: defaultFilePerms(),
        };
    }

    togglePerm(row: SurfaceFileRow, key: keyof SurfaceFilePerms): void {
        if (this.readOnly()) return;
        this.fileRows.update((rows) =>
            rows.map((r) => (r.id === row.id ? { ...r, perms: { ...r.perms, [key]: nextPermState(r.perms[key]) } } : r))
        );
        this.emitStorageChange();
    }

    columnPermState(key: keyof SurfaceFilePerms): PermTriState {
        const rows = this.fileRows();
        if (!rows.length) return 'unset';
        const first = rows[0].perms[key];
        return rows.every((r) => r.perms[key] === first) ? first : 'unset';
    }

    toggleColumnPerm(key: keyof SurfaceFilePerms): void {
        if (this.readOnly()) return;
        const next = nextPermState(this.columnPermState(key));
        this.fileRows.update((rows) => rows.map((r) => ({ ...r, perms: { ...r.perms, [key]: next } })));
        this.emitStorageChange();
    }

    removeFileRow(row: SurfaceFileRow, event: MouseEvent): void {
        if (this.readOnly()) return;
        event.stopPropagation();
        this.fileRows.update((rows) => rows.filter((r) => r.id !== row.id));
        this.emitStorageChange();
    }

    clearFiles(): void {
        if (this.readOnly()) return;
        this.fileRows.update((rows) =>
            rows.map((r) => ({ ...r, perms: { list: 'unset', view: 'unset', edit: 'unset', delete: 'unset' } }))
        );
        this.emitStorageChange();
    }

    clearAllFiles(event: MouseEvent): void {
        event.stopPropagation();
        this.confirmClearBundle('files', this.fileRows().length, () => {
            this.fileRows.set([]);
            this.emitStorageChange();
        });
    }

    openAddFiles(): void {
        if (this.readOnly()) return;
        this.dialog
            .open<CreateFolderDialogResult>(CreateFolderDialogComponent)
            .closed.pipe(take(1))
            .subscribe((result) => {
                if (result?.type === 'upload') this.reloadStorageRoot();
            });
    }

    selectAllFilePerms(): void {
        if (this.readOnly()) return;
        this.fileRows.update((rows) =>
            rows.map((r) => ({ ...r, perms: { list: 'allow', view: 'allow', edit: 'allow', delete: 'allow' } }))
        );
        this.emitStorageChange();
    }

    readonly fileDropActive = signal<boolean>(false);

    private canAcceptFileDrop(): boolean {
        return this.storageDrag.isDragging() && !this.readOnly();
    }

    /** Spring-load: a storage item hovered over a collapsed card opens it on the Files tab. */
    onStorageDragHover(): void {
        if (!this.canAcceptFileDrop()) return;
        if (!this.expanded() && !this.hideHeader()) this.expanded.set(true);
        this.activeTab.set('files');
    }

    onStorageDragOver(event: DragEvent): void {
        if (!this.canAcceptFileDrop()) return;
        event.preventDefault();
        event.stopPropagation();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        this.fileDropActive.set(true);
    }

    onStorageDragLeave(event: DragEvent): void {
        const host = event.currentTarget as HTMLElement;
        const related = event.relatedTarget as Node | null;
        if (related && host.contains(related)) return;
        this.fileDropActive.set(false);
    }

    onStorageDrop(event: DragEvent): void {
        this.fileDropActive.set(false);
        if (!this.canAcceptFileDrop()) return;
        event.preventDefault();
        event.stopPropagation();
        const dragged = this.storageDrag.dragged();
        this.storageDrag.end();
        if (!dragged) return;
        if (!this.expanded() && !this.hideHeader()) this.expanded.set(true);
        this.activeTab.set('files');
        this.catalogs
            .loadStorageTree()
            .pipe(take(1), takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.addDroppedItem(dragged));
    }

    private addDroppedItem(item: StorageItem): void {
        // No cascade: a dropped folder adds ONLY the folder entry (its own id), never its files.
        const resolved = this.resolveDroppedEntry(item);
        if (resolved == null) {
            this.toast.info(`Could not find "${item.name}" in storage`);
            return;
        }
        if (this.fileRows().some((r) => r.id === resolved)) {
            this.toast.info(`"${item.name}" is already in this surface`);
            return;
        }
        this.fileRows.update((rows) => [...rows, this.newFileRow(resolved, item.type)]);
        this.emitStorageChange();
    }

    private resolveDroppedEntry(item: StorageItem): number | null {
        if (item.type === 'file') {
            if (typeof item.id === 'number') return item.id;
            for (const [id, m] of this.catalogs.storageFileMeta()) {
                if (m.type === 'file' && m.path === item.path) return id;
            }
            return null;
        }
        return typeof item.id === 'number' ? item.id : this.catalogs.folderIdForPath(item.path);
    }

    private buildStoragePayload(): SurfaceStorageItem[] {
        return this.fileRows().map((r) => ({
            storage_file: r.id,
            can_list: r.perms.list,
            can_view: r.perms.view,
            can_edit: r.perms.edit,
            can_delete: r.perms.delete,
        }));
    }

    private emitStorageChange(): void {
        const payload = this.buildStoragePayload();
        this.lastSentStorageItems = serializeStorageItems(payload);
        if (this.isCreating()) {
            this.notifyDraftContent();
            return;
        }
        this.surfaceChange.emit({ storage_items: payload });
    }

    onCollectionsChange(values: unknown[]): void {
        if (this.readOnly()) return;
        const ids = values as number[];
        const byId = new Map(this.knowledgeItems().map((k) => [k.collection, k]));
        this.knowledgeItems.set(ids.map((id) => byId.get(id) ?? { collection: id }));
        this.emitKnowledgeChange();
        this.revealAdvancedIfRagMissing();
    }

    onKnowledgeConfigChange(item: SurfaceKnowledge): void {
        if (this.readOnly()) return;
        this.knowledgeItems.update((items) => items.map((k) => (k.collection === item.collection ? item : k)));
        this.emitKnowledgeChange();
    }

    removeCollection(id: number, event: MouseEvent): void {
        if (this.readOnly()) return;
        event.stopPropagation();
        this.knowledgeItems.update((items) => items.filter((k) => k.collection !== id));
        this.emitKnowledgeChange();
    }

    clearCollections(event: MouseEvent): void {
        event.stopPropagation();
        this.confirmClearBundle('collections', this.selectedCollectionIds().size, () => {
            this.knowledgeItems.set([]);
            this.emitKnowledgeChange();
        });
    }

    openAddCollection(): void {
        if (this.readOnly()) return;
        this.collectionsStorage
            .createCollection()
            .pipe(
                take(1),
                switchMap(({ collection_id }) =>
                    this.dialog
                        .open(CreateCollectionDialogComponent, {
                            width: 'calc(100vw - 2rem)',
                            height: 'calc(100vh - 2rem)',
                            data: { collection_id },
                            disableClose: true,
                        })
                        .closed.pipe(
                            take(1),
                            map(() => collection_id)
                        )
                ),
                switchMap((collection_id) =>
                    this.catalogs.reloadCollections().pipe(
                        take(1),
                        map((cols) => ({ collection_id, cols }))
                    )
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(({ collection_id, cols }) => {
                if (collection_id == null || !cols.some((c) => c.id === collection_id)) return;
                this.knowledgeItems.update((items) =>
                    items.some((k) => k.collection === collection_id)
                        ? items
                        : [...items, { collection: collection_id }]
                );
                this.emitKnowledgeChange();
                this.revealAdvancedIfRagMissing();
            });
    }

    private clearSentSnapshots(): void {
        this.lastSentName = null;
        this.lastSentInstructions = null;
        this.lastSentToolKeys = null;
        this.lastSentKnowledge = null;
        this.lastSentStorageItems = null;
    }

    private hasRag(k: SurfaceKnowledge): boolean {
        return !!(k.naive_search_config || k.graph_basic_search_config || k.graph_local_search_config);
    }

    private revealAdvancedIfRagMissing(): void {
        if (this.readOnly()) return;
        if (this.collectionsWithoutRag().size > 0) this.collectionAdvancedOpen.set(true);
    }

    // Only collections with a RAG chosen are persisted; RAG-less rows stay in the UI (with a
    // "Select RAG" hint) until configured, so we never send a row the backend would reject.
    private buildKnowledgePayload(): SurfaceKnowledge[] {
        return this.knowledgeItems().filter((k) => this.hasRag(k));
    }

    private emitKnowledgeChange(): void {
        const payload = this.buildKnowledgePayload();
        this.lastSentKnowledge = serializeKnowledge(payload);
        if (this.isCreating()) {
            this.notifyDraftContent();
            return;
        }
        this.surfaceChange.emit({ knowledge: payload });
    }

    toggleCollectionAdvanced(): void {
        this.collectionAdvancedOpen.update((v) => !v);
    }

    onSave(): void {
        this.save.emit();
    }

    onCancel(): void {
        this.cancel.emit();
    }

    toggleFolder(path: string, event: MouseEvent): void {
        event.stopPropagation();
        this.collapsedFolderPaths.update((set) => {
            const next = new Set(set);
            if (next.has(path)) next.delete(path);
            else next.add(path);
            return next;
        });
    }

    fileTrackBy(_i: number, row: SurfaceFileRow): number {
        return row.id;
    }

    displayRowTrackBy(_i: number, row: SurfaceFileDisplayRow): string {
        if (row.kind === 'file') return `file:${row.row.id}`;
        return row.row ? `folder:${row.row.id}` : `folder-path:${row.path}`;
    }
}

function defaultFilePerms(): SurfaceFilePerms {
    return { list: 'allow', view: 'allow', edit: 'allow', delete: 'unset' };
}

function serializeToolKeys(keys: Set<string>): string {
    return JSON.stringify([...keys].sort());
}

function serializeStorageItems(items: SurfaceStorageItem[]): string {
    return JSON.stringify(
        [...items]
            .sort((a, b) => a.storage_file - b.storage_file)
            .map((si) => [si.storage_file, si.can_list, si.can_view, si.can_edit, si.can_delete])
    );
}

function serializeKnowledge(items: SurfaceKnowledge[]): string {
    return JSON.stringify([...items].map((k) => k.collection).sort((a, b) => a - b));
}
