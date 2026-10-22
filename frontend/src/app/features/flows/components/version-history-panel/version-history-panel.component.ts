import { OverlayModule } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    HostListener,
    inject,
    input,
    OnInit,
    output,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';
import {
    AppSvgIconComponent,
    BulkSelectDropdownComponent,
    ButtonComponent,
    CheckboxComponent,
    IconButtonComponent,
    SpinnerComponent,
} from '@shared/components';
import { HasPermissionDirective, TooltipOnOverflowDirective } from '@shared/directives';
import {
    ActionCode,
    BulkDeleteGroup,
    BulkDeleteItem,
    BulkDeleteLabel,
    BulkDeleteTarget,
    ResourceCode,
} from '@shared/models';
import { BulkDeleteService } from '@shared/services';
import { Subscription } from 'rxjs';
import { finalize, tap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { GraphVersionDto } from '../../models/graph.model';
import { CreateGraphWarningsService } from '../../services/create-graph-warnings.service';
import { FlowsApiService } from '../../services/flows-api.service';

const VERSION_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'version', plural: 'versions' };

/** How long a click on the renameable name/description waits for a second click (double-click = rename). */
const RENAME_DOUBLE_CLICK_WINDOW_MS = 250;

@Component({
    selector: 'app-version-history-panel',
    imports: [
        IconButtonComponent,
        CommonModule,
        FormsModule,
        SpinnerComponent,
        AppSvgIconComponent,
        MatTooltipModule,
        OverlayModule,
        ButtonComponent,
        BulkSelectDropdownComponent,
        CheckboxComponent,
        HasPermissionDirective,
        TooltipOnOverflowDirective,
    ],
    templateUrl: './version-history-panel.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrl: './version-history-panel.component.scss',
})
export class VersionHistoryPanelComponent implements OnInit {
    public versionsList: GraphVersionDto[] = [];
    public isLoading = true;
    public openMenuId: number | null = null;
    public editingVersionId: number | null = null;
    public editingField: 'name' | 'description' | null = null;
    public editingValue: string = '';
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
    private editingVersion: GraphVersionDto | null = null;
    private isSaving = false;
    private pendingPreviewTimer: ReturnType<typeof setTimeout> | null = null;
    /** Only the latest load may write the list: an older, slower load must not overwrite a newer one. */
    private versionsLoadSubscription: Subscription | null = null;

    public readonly selectMode = signal(false);
    public readonly selectedVersionIds = signal<ReadonlySet<number>>(new Set());
    public readonly isDeleting = signal(false);
    public readonly selectedCount = computed(() => this.selectedVersionIds().size);

    @ViewChild('versionEditInput') editInput?: ElementRef<HTMLInputElement>;

    private destroyRef = inject(DestroyRef);
    private bulkDeleteService = inject(BulkDeleteService);

    private readonly bulkDeleteTarget: BulkDeleteTarget = {
        previewBulkDelete: (ids) => this.flowApiService.bulkDeleteGraphVersions(ids, { dryRun: true }),
        bulkDelete: (ids) =>
            this.flowApiService
                .bulkDeleteGraphVersions(ids)
                .pipe(tap((response) => this.removeVersions([...response.deleted_ids, ...response.not_found_ids]))),
        removeFromCache: (ids) => this.removeVersions(ids),
    };

    public graphId = input.required<number>();
    public graphSaveVersion = input<number | undefined>();
    public hasUnsavedChanges = input<boolean>(false);
    /** Version currently shown in the canvas preview (owned by the parent); highlights its card. */
    public readonly previewedVersionId = input<number | null>(null);
    /** Selected card (owned by the parent, set only once it accepts a preview); the footer "Restore This Version" acts on it. */
    public readonly selectedVersionId = input<number | null>(null);

    public closed = output<void>();
    public restoreRequested = output<GraphVersionDto>();
    public readonly previewRequested = output<GraphVersionDto>();
    public readonly versionDeleted = output<GraphVersionDto>();
    public readonly versionUpdated = output<GraphVersionDto>();

    @HostListener('document:mousedown', ['$event'])
    onDocumentMouseDown(event: MouseEvent): void {
        const editing = this.editingVersion;
        if (!editing) return;
        if (this.editInput && !this.editInput.nativeElement.contains(event.target as Node)) {
            this.saveEdit(editing);
        }
    }

    constructor(
        private flowApiService: FlowsApiService,
        private toastService: ToastService,
        private cdr: ChangeDetectorRef,
        private router: Router,
        private createGraphWarningsService: CreateGraphWarningsService
    ) {
        this.destroyRef.onDestroy(() => this.cancelPendingPreview());
    }

    public ngOnInit(): void {
        this.loadVersions();
    }

    public toggleMenu(id: number): void {
        this.openMenuId = this.openMenuId === id ? null : id;
    }

    public onCardClick(event: MouseEvent, version: GraphVersionDto): void {
        // The second click of a double-click; the first one already opened the preview or toggled the card.
        if (event.detail > 1) return;
        if (this.selectMode()) {
            this.toggleVersionSelection(version.id);
            return;
        }
        this.openPreview(version);
    }

    /**
     * A double-click on the name/description starts a rename, and it fires two clicks first.
     * Wait out the double-click window so a rename never opens the preview (or moves the selection).
     */
    public onRenameableTextClick(event: MouseEvent, version: GraphVersionDto): void {
        event.stopPropagation();
        if (event.detail > 1) return;
        if (this.selectMode()) {
            this.toggleVersionSelection(version.id);
            return;
        }
        this.cancelPendingPreview();
        this.pendingPreviewTimer = setTimeout(() => {
            this.pendingPreviewTimer = null;
            this.openPreview(version);
        }, RENAME_DOUBLE_CLICK_WINDOW_MS);
    }

    public onCardKeydown(event: KeyboardEvent, version: GraphVersionDto): void {
        // Keys typed into the rename inputs or the options button bubble up here — only the card itself reacts.
        if (event.target !== event.currentTarget) return;
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        if (this.selectMode()) {
            this.toggleVersionSelection(version.id);
            return;
        }
        this.openPreview(version);
    }

    /** In select mode a card shows the bulk selection; otherwise the version the parent selected. */
    public isCardSelected(id: number): boolean {
        return this.selectMode() ? this.isVersionSelected(id) : this.selectedVersionId() === id;
    }

    public enterSelectMode(): void {
        this.setSelectMode(true);
    }

    public cancelSelectMode(): void {
        this.setSelectMode(false);
    }

    public isVersionSelected(id: number): boolean {
        return this.selectedVersionIds().has(id);
    }

    public areAllVersionsSelected(): boolean {
        const selectedIds = this.selectedVersionIds();
        return this.versionsList.length > 0 && this.versionsList.every((version) => selectedIds.has(version.id));
    }

    public toggleSelectAll(): void {
        if (this.isDeleting()) return;

        this.selectedVersionIds.set(
            this.areAllVersionsSelected() ? new Set() : new Set(this.versionsList.map((version) => version.id))
        );
    }

    public toggleVersionSelection(id: number): void {
        if (this.isDeleting()) return;

        const next = new Set(this.selectedVersionIds());
        if (next.has(id)) {
            next.delete(id);
        } else {
            next.add(id);
        }
        this.selectedVersionIds.set(next);
    }

    public restoreVersion(version: GraphVersionDto, event?: MouseEvent): void {
        event?.stopPropagation();
        this.openMenuId = null;
        this.restoreRequested.emit(version);
    }

    public restoreSelectedVersion(): void {
        const version = this.versionsList.find((v) => v.id === this.selectedVersionId());
        if (!version) return;

        const pendingName =
            this.editingVersionId === version.id && this.editingField === 'name' && this.editingValue.trim()
                ? this.editingValue.trim()
                : null;

        this.restoreRequested.emit(pendingName ? { ...version, name: pendingName } : version);
    }

    public startEdit(version: GraphVersionDto, field: 'name' | 'description'): void {
        // While selecting, a double-click on the name/description is one toggle, never a rename.
        if (this.selectMode()) return;
        this.cancelPendingPreview();
        this.openMenuId = null;
        this.editingVersion = version;
        this.editingVersionId = version.id;
        this.editingField = field;
        this.editingValue = field === 'name' ? version.name : version.description || '';
        this.cdr.detectChanges();
        setTimeout(() => {
            this.editInput?.nativeElement.focus();
        });
    }

    public saveEdit(version: GraphVersionDto): void {
        if (!this.editingVersionId || !this.editingField || this.isSaving) return;

        const field = this.editingField;
        const value = this.editingValue.trim();
        const originalValue = field === 'name' ? version.name : version.description || '';

        if (field === 'name' && !value) {
            this.toastService.warning('Version name is required');
            this.cancelEdit();
            return;
        }
        if (value === originalValue) {
            this.cancelEdit();
            return;
        }

        this.isSaving = true;

        const payload =
            field === 'name'
                ? { name: value, description: version.description || '' }
                : { name: version.name, description: value };

        this.flowApiService
            .updateGraphVersion(version.id, payload)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (updated) => {
                    const idx = this.versionsList.findIndex((v) => v.id === version.id);
                    if (idx !== -1) {
                        this.versionsList[idx] = updated;
                    }
                    this.versionUpdated.emit(updated);
                    this.toastService.success(field === 'name' ? 'Version was renamed' : 'Description was updated');
                    this.cancelEdit();
                },
                error: () => {
                    this.toastService.error('Failed to update version');
                    this.isSaving = false;
                },
                complete: () => {
                    this.isSaving = false;
                },
            });
    }

    public cancelEdit(): void {
        this.editingVersionId = null;
        this.editingField = null;
        this.editingValue = '';
        this.editingVersion = null;
    }

    public onEditKeydown(event: KeyboardEvent, version: GraphVersionDto): void {
        if (event.key === 'Enter') {
            event.preventDefault();
            this.saveEdit(version);
        } else if (event.key === 'Escape') {
            this.cancelEdit();
        }
    }

    public deleteVersion(version: GraphVersionDto, event?: MouseEvent): void {
        event?.stopPropagation();
        this.openMenuId = null;

        this.bulkDeleteService
            .run([this.buildDeleteGroup([{ id: version.id, name: version.name }])])
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe();
    }

    public deleteSelectedVersions(): void {
        const selectedIds = this.selectedVersionIds();
        const items = this.versionsList
            .filter((version) => selectedIds.has(version.id))
            .map((version) => ({ id: version.id, name: version.name }));
        if (items.length === 0) return;

        this.isDeleting.set(true);
        this.bulkDeleteService
            .run([this.buildDeleteGroup(items)])
            .pipe(
                tap(() => this.setSelectMode(false)),
                finalize(() => this.isDeleting.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    public loadVersions(): void {
        this.versionsLoadSubscription?.unsubscribe();
        this.versionsLoadSubscription = this.flowApiService
            .getGraphVersions(this.graphId())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => {
                    this.versionsList = result;
                    this.isLoading = false;
                },
                error: (err) => {
                    console.error('Failed to load graph versions', err);
                    this.isLoading = false;
                },
            });
    }

    public createFlowFromVersion(version: GraphVersionDto, $event: MouseEvent): void {
        $event.stopPropagation();
        this.openMenuId = null;
        this.flowApiService
            .createGraphFromVersion(version.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    this.toastService.success('New flow created');
                    if (response.warnings.length) {
                        this.createGraphWarningsService.setPending(response.warnings);
                    }
                    this.closed.emit();
                    this.router.navigate(['/flows', response.graph_id]);
                },
                error: () => this.toastService.error('Failed to create flow'),
            });
    }

    private buildDeleteGroup(items: BulkDeleteItem[]): BulkDeleteGroup {
        return { target: this.bulkDeleteTarget, label: VERSION_BULK_DELETE_LABEL, items };
    }

    /** Single place both `enterSelectMode` and `cancelSelectMode`/delete-completion go through,
     *  so the open ⋮ menu never survives a select-mode transition and reopens unexpectedly,
     *  and a preview waiting out the double-click window never opens after selecting starts. */
    private setSelectMode(mode: boolean): void {
        this.openMenuId = null;
        this.cancelPendingPreview();
        this.selectMode.set(mode);
        if (!mode) {
            this.selectedVersionIds.set(new Set());
        }
    }

    /** Drops deleted versions from the list. The parent owns the preview and the selected version,
     *  so it learns of each removal through `versionDeleted`. */
    private removeVersions(ids: number[]): void {
        if (ids.length === 0) return;

        const idSet = new Set(ids);
        const removed = this.versionsList.filter((version) => idSet.has(version.id));
        this.versionsList = this.versionsList.filter((version) => !idSet.has(version.id));
        removed.forEach((version) => this.versionDeleted.emit(version));

        const currentSelection = this.selectedVersionIds();
        if ([...currentSelection].some((id) => idSet.has(id))) {
            const nextSelection = new Set(currentSelection);
            idSet.forEach((id) => nextSelection.delete(id));
            this.selectedVersionIds.set(nextSelection);
        }
    }

    /** Asks the parent to preview the version; the parent selects it only if it accepts, so selection == previewed version. */
    private openPreview(version: GraphVersionDto): void {
        this.cancelPendingPreview();
        this.previewRequested.emit(version);
    }

    private cancelPendingPreview(): void {
        if (this.pendingPreviewTimer === null) return;
        clearTimeout(this.pendingPreviewTimer);
        this.pendingPreviewTimer = null;
    }
}
