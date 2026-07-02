import { Dialog } from '@angular/cdk/dialog';
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
    ConfirmationDialogService,
    SelectDropdownComponent,
    SelectDropdownHeaderAction,
    SelectDropdownListItem,
    SelectDropdownTab,
    SelectDropdownTriggerDirective,
} from '@shared/components';
import { EnterBlurDirective } from '@shared/directives';
import { map, switchMap, take } from 'rxjs/operators';

import { CreateCustomToolDialogComponent } from '../../../../../../../../user-settings-page/tools/custom-tool-editor/create-custom-tool-dialog/create-custom-tool-dialog.component';
import {
    CreateFolderDialogComponent,
    CreateFolderDialogResult,
} from '../../../../../../../files/components/create-folder-dialog/create-folder-dialog.component';
import { StorageApiService } from '../../../../../../../files/services/storage-api.service';
import { CreateCollectionDialogComponent } from '../../../../../../../knowledge-sources/components/create-collection-dialog/create-collection-dialog.component';
import { CollectionsStorageService } from '../../../../../../../knowledge-sources/services/collections-storage.service';
import { McpToolDialogComponent } from '../../../../../../../tools/components/mcp-tool-dialog/mcp-tool-dialog.component';
import { GetMcpToolRequest } from '../../../../../../../tools/models/mcp-tool.model';
import { GetPythonCodeToolRequest } from '../../../../../../../tools/models/python-code-tool.model';
import { AgentDefinition } from '../../../../../../models/agent-definition.model';
import {
    CreateSurfaceRequest,
    PartialUpdateSurfaceRequest,
    PermTriState,
    Surface,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfacePythonTool,
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
import { SURFACE_CATEGORIES, SurfaceCategoryId } from '../../../../../../models/surface-category.model';
import { StorageFileMeta, SurfaceCatalogsStore } from '../../../../../../services/surface-catalogs-store.service';
import { DELETE_CONFIRM_DIALOG_WIDTH } from '../../../../../../utils/delete-confirmation.util';
import {
    buildClearSurfaceBundleDialog,
    SurfaceBundleClearKind,
} from '../../../../../../utils/surface-bundle-confirmation.util';
import {
    buildSurfaceFileDisplayRows,
    buildSurfaceFileStats,
    filesInFolder,
} from '../../../../../../utils/surface-file-tree.util';

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
    ],
    templateUrl: './surface-card.component.html',
    styleUrls: ['./surface-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SurfaceCardComponent {
    private readonly catalogs: SurfaceCatalogsStore = inject(SurfaceCatalogsStore);
    private readonly storageApi: StorageApiService = inject(StorageApiService);
    private readonly collectionsStorage: CollectionsStorageService = inject(CollectionsStorageService);
    private readonly destroyRef: DestroyRef = inject(DestroyRef);
    private readonly dialog: Dialog = inject(Dialog);
    private readonly confirm: ConfirmationDialogService = inject(ConfirmationDialogService);

    surface = input<Surface | null>(null);
    readOnly = input<boolean>(false);
    showMeta = input<boolean>(false);
    agents = input<AgentDefinition[]>([]);

    expanded = model<boolean>(false);
    isShared = input<boolean>(false);
    currentPlace = input<SurfaceCategoryId | null>(null);
    draggable = input<boolean>(false);
    hideHeader = input<boolean>(false);
    isCreating = input<boolean>(false);

    readonly save = output<void>();
    readonly cancel = output<void>();
    readonly surfaceChange = output<PartialUpdateSurfaceRequest>();
    readonly renameSurface = output<string>();
    readonly createDraft = output<CreateSurfaceRequest>();
    readonly openSource = output<void>();
    readonly detach = output<void>();
    readonly makeShared = output<void>();
    readonly makeAgentSpecificCopy = output<void>();
    readonly moveSurfacePlace = output<SurfaceCategoryId>();
    readonly duplicate = output<void>();
    readonly deleteSurface = output<void>();

    readonly activeTab = signal<SurfaceTabId>('tools');
    readonly instructions = signal<string>('');

    readonly menuOpen = signal<boolean>(false);
    private readonly instructionsTextarea = viewChild<ElementRef<HTMLTextAreaElement>>('instrTa');
    private editedName = '';

    readonly moveTargets = computed(() => {
        if (!this.isShared() || !this.readOnly()) return [];
        const current = this.currentPlace();
        return SURFACE_CATEGORIES.filter((c) => c.id !== current).map((c) => ({
            place: c.id,
            label: c.moveLabel,
        }));
    });

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
        this.editedName = value;
    }

    commitRename(): void {
        const name = this.editedName.trim();
        const current = this.surface()?.name ?? '';
        if (!name || name === current) return;
        if (this.isCreating()) {
            this.createDraft.emit(this.buildCreateRequest(name));
            return;
        }
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

    onMoveToPlace(place: SurfaceCategoryId, event: MouseEvent): void {
        event.stopPropagation();
        this.menuOpen.set(false);
        this.moveSurfacePlace.emit(place);
    }

    readonly assignedAgentChips = computed<{ id: number; name: string }[]>(() => {
        const id = this.surface()?.id;
        if (id == null) return [];
        return this.agents()
            .filter((a) => a.default_surfaces.some((ds) => ds.surface === id))
            .map((a) => ({ id: a.id, name: a.name }));
    });

    readonly toolsExpanded = signal<boolean>(false);
    readonly filesExpanded = signal<boolean>(false);
    readonly collectionsExpanded = signal<boolean>(false);

    readonly toolOptions = computed<SurfaceToolOption[]>(() => [
        ...this.catalogs.pythonTools(),
        ...this.catalogs.mcpTools(),
    ]);
    readonly selectedToolKeys = signal<Set<string>>(new Set());

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

    readonly selectedFileIds = computed<number[]>(() => this.fileRows().map((r) => r.id));

    readonly fileStats = computed(() => buildSurfaceFileStats(this.fileRows()));

    readonly displayFileRows = computed(() =>
        buildSurfaceFileDisplayRows(this.fileRows(), this.collapsedFolderPaths())
    );

    readonly collectionOptions = this.catalogs.collections;
    readonly selectedCollectionIds = signal<Set<number>>(new Set());
    readonly collectionAdvancedOpen = signal<boolean>(false);

    readonly collectionHeaderAction: SelectDropdownHeaderAction = { icon: 'plus', label: 'Add new collection' };

    readonly collectionItems = computed<SelectDropdownListItem<number>[]>(() =>
        this.collectionOptions().map((c) => ({ name: c.name, value: c.id }))
    );
    readonly selectedCollectionValues = computed<number[]>(() => [...this.selectedCollectionIds()]);
    readonly selectedCollections = computed<SurfaceCollectionOption[]>(() =>
        this.collectionOptions().filter((c) => this.selectedCollectionIds().has(c.id))
    );

    constructor() {
        effect(() => {
            const s = this.surface();
            this.instructions.set(s?.instructions ?? '');
            const toolKeys = new Set<string>([
                ...(s?.python_tools ?? []).map((t) => `python:${t.python_tool}`),
                ...(s?.mcp_tools ?? []).map((t) => `mcp:${t.mcp_tool}`),
            ]);
            this.selectedToolKeys.set(toolKeys);
            this.selectedCollectionIds.set(new Set((s?.knowledge ?? []).map((k) => k.collection)));
            this.fileRows.set(
                (s?.storage_items ?? []).map((si) => {
                    const meta = untracked(() => this.metaFor(si.storage_file));
                    return {
                        id: si.storage_file,
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
        });

        effect(() => {
            if (!this.expanded()) return;
            this.loadCatalogs();
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
                        for (const f of files) this.fileMetaById.set(f.id, { name: f.name, path: f.path });
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
                return meta ? { ...r, name: meta.name, path: meta.path } : r;
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

    onInstructionsBlur(): void {
        if (this.isCreating()) return;
        const value = this.instructions();
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
        if (this.isCreating()) return;
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

    onFilesChange(values: unknown[]): void {
        if (this.readOnly()) return;
        const keep = (values as (number | string)[]).filter((v): v is number => typeof v === 'number');
        const byId = new Map(this.fileRows().map((r) => [r.id, r]));
        const next: SurfaceFileRow[] = keep.map((id) => {
            const existing = byId.get(id);
            if (existing) return existing;
            const meta = this.metaFor(id);
            return {
                id,
                name: meta?.name ?? `File #${id}`,
                path: meta?.path ?? '',
                perms: defaultFilePerms(),
            };
        });
        this.fileRows.set(next);
        this.emitStorageChange();
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
        if (this.isCreating()) return;
        this.surfaceChange.emit({ storage_items: this.buildStoragePayload() });
    }

    onCollectionsChange(values: unknown[]): void {
        if (this.readOnly()) return;
        this.selectedCollectionIds.set(new Set(values as number[]));
        this.emitKnowledgeChange();
    }

    removeCollection(id: number, event: MouseEvent): void {
        if (this.readOnly()) return;
        event.stopPropagation();
        this.selectedCollectionIds.update((set) => {
            const next = new Set(set);
            next.delete(id);
            return next;
        });
        this.emitKnowledgeChange();
    }

    clearCollections(event: MouseEvent): void {
        event.stopPropagation();
        this.confirmClearBundle('collections', this.selectedCollectionIds().size, () => {
            this.selectedCollectionIds.set(new Set());
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
                this.selectedCollectionIds.update((set) => new Set([...set, collection_id]));
                this.emitKnowledgeChange();
            });
    }

    private buildKnowledgePayload(): SurfaceKnowledge[] {
        return [...this.selectedCollectionIds()].map((collection) => ({ collection }));
    }

    private emitKnowledgeChange(): void {
        if (this.isCreating()) return;
        this.surfaceChange.emit({ knowledge: this.buildKnowledgePayload() });
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

    folderPermState(folderPath: string, key: keyof SurfaceFilePerms): PermTriState {
        const descendants = filesInFolder(this.fileRows(), folderPath);
        if (!descendants.length) return 'unset';
        const states = descendants.map((file) => file.perms[key]);
        const first = states[0];
        return states.every((state) => state === first) ? first : 'unset';
    }

    toggleFolderPerm(folderPath: string, key: keyof SurfaceFilePerms): void {
        if (this.readOnly()) return;
        const descendants = filesInFolder(this.fileRows(), folderPath);
        if (!descendants.length) return;
        const next = nextPermState(this.folderPermState(folderPath, key));
        const ids = new Set(descendants.map((file) => file.id));
        this.fileRows.update((rows) =>
            rows.map((row) => (ids.has(row.id) ? { ...row, perms: { ...row.perms, [key]: next } } : row))
        );
        this.emitStorageChange();
    }

    fileTrackBy(_i: number, row: SurfaceFileRow): number {
        return row.id;
    }

    displayRowTrackBy(_i: number, row: SurfaceFileDisplayRow): string {
        return row.kind === 'folder' ? `folder:${row.path}` : `file:${row.row.id}`;
    }
}

function defaultFilePerms(): SurfaceFilePerms {
    return { list: 'allow', view: 'allow', edit: 'allow', delete: 'unset' };
}
