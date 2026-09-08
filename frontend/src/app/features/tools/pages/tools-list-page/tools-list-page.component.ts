import { Dialog } from '@angular/cdk/dialog';
import { OverlayModule } from '@angular/cdk/overlay';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    HostListener,
    inject,
    OnDestroy,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import {
    AppCustomFilterDialogComponent,
    AppCustomFilterDialogData,
    AppCustomFilterDialogResult,
    AppSvgIconComponent,
    ButtonComponent,
    LabelSidebarComponent,
    SearchComponent,
    TabButtonComponent,
    ToggleSwitchComponent,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { LABELS_STORE } from '@shared/services';
import { filter } from 'rxjs/operators';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { HideInlineSubtitleOnOverflowDirective } from '../../../../shared/directives/hide-inline-subtitle-on-overflow.directive';
import { ToolsLabelsStorageService } from '../../services/tools-labels-storage.service';
import { ToolsSearchService } from '../../services/tools-search.service';
import { ToolsViewStorageService } from '../../services/tools-view-storage.service';
import {
    ToolsBulkAction,
    ToolsBulkActionsMenuComponent,
} from './components/tools-bulk-actions-menu/tools-bulk-actions-menu.component';
import {
    ToolsFilterMenuAction,
    ToolsFilterMenuComponent,
} from './components/tools-filter-menu/tools-filter-menu.component';

@Component({
    selector: 'app-tools-list-page',
    imports: [
        RouterOutlet,
        RouterLink,
        RouterLinkActive,
        TabButtonComponent,
        ButtonComponent,
        FormsModule,
        AppSvgIconComponent,
        HideInlineSubtitleOnOverflowDirective,
        MatTooltipModule,
        HasPermissionDirective,
        OverlayModule,
        LabelSidebarComponent,
        ToolsFilterMenuComponent,
        ToolsBulkActionsMenuComponent,
        ToggleSwitchComponent,
        SearchComponent,
    ],
    templateUrl: './tools-list-page.component.html',
    styleUrls: ['./tools-list-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [{ provide: LABELS_STORE, useExisting: ToolsLabelsStorageService }],
})
export class ToolsListPageComponent implements OnDestroy, OnInit {
    public tabs = [
        { label: 'Custom', link: 'custom' },
        { label: 'MCP', link: 'mcp' },
    ];

    public searchTerm: string = '';

    public showSidebar = signal<boolean>(true);
    public filterMenuOpen = signal<boolean>(false);
    public bulkMenuOpen = signal<boolean>(false);

    private readonly isMouseOnBulkButton = signal<boolean>(false);
    private readonly isMouseOnBulkMenu = signal<boolean>(false);
    private readonly isBulkLabelsOpen = signal<boolean>(false);
    private bulkCloseTimeout: ReturnType<typeof setTimeout> | null = null;

    private readonly dialog = inject(Dialog);
    private readonly permissionService = inject(PermissionsService);
    private readonly router = inject(Router);
    private readonly destroyRef = inject(DestroyRef);
    private readonly toolsSearchService = inject(ToolsSearchService);
    private readonly labelsStorage = inject(ToolsLabelsStorageService);
    public readonly viewState = inject(ToolsViewStorageService);

    private readonly noSelectionActions: ToolsBulkAction[] = [
        {
            label: 'Select All',
            kind: 'select-all',
            isPermitted: true,
        },
        {
            label: 'Delete All Unused',
            kind: 'delete-unused',
            isPermitted: this.permissionService.can(ResourceCode.Tools, ActionCode.Delete),
        },
    ];

    // "Add Label" is rendered by the bulk-actions-menu itself (label-dropdown trigger),
    // not as a plain action here.
    private readonly selectionActions: ToolsBulkAction[] = [
        {
            label: 'Select All',
            kind: 'select-all',
            isPermitted: true,
        },
        {
            label: 'Make Favorite',
            kind: 'favorite',
            isPermitted: true,
        },
        {
            label: 'Duplicate',
            kind: 'duplicate',
            isPermitted: this.permissionService.can(ResourceCode.Tools, ActionCode.Create),
        },
        {
            label: 'Export Selected',
            kind: 'export-selected',
            isPermitted: this.permissionService.can(ResourceCode.Tools, ActionCode.Export),
        },
        {
            label: 'Delete All Selected',
            kind: 'delete-selected',
            isPermitted: this.permissionService.can(ResourceCode.Tools, ActionCode.Delete),
        },
    ];

    public readonly hasSelection = this.viewState.hasSelection;
    public readonly canUpdateTools = this.permissionService.can(ResourceCode.Tools, ActionCode.Update);

    public readonly bulkActions = computed<ToolsBulkAction[]>(() =>
        this.hasSelection() ? this.selectionActions : this.noSelectionActions
    );

    /**
     * Labels applied to *every* currently selected tool. Rendered as fully
     * checked in the bulk "Manage Labels" dropdown.
     */
    public readonly commonSelectedLabelIds = computed<number[]>(() => {
        const rows = this.viewState.selectedToolsMeta();
        if (rows.length === 0) return [];
        const iter = rows.map((r) => new Set<number>(r.labels));
        const intersection = new Set<number>(iter[0]);
        for (let i = 1; i < iter.length; i++) {
            for (const id of intersection) if (!iter[i].has(id)) intersection.delete(id);
        }
        return [...intersection];
    });

    /**
     * Labels applied to some (but not all) selected tools. Rendered as
     * indeterminate in the bulk "Manage Labels" dropdown.
     */
    public readonly partialSelectedLabelIds = computed<number[]>(() => {
        const rows = this.viewState.selectedToolsMeta();
        if (rows.length === 0) return [];
        const union = new Set<number>();
        for (const r of rows) for (const id of r.labels) union.add(id);
        const common = new Set<number>(this.commonSelectedLabelIds());
        return [...union].filter((id) => !common.has(id));
    });

    public readonly activeLabelFilterDisplay = computed(() => {
        const filter = this.labelsStorage.activeLabelFilter();
        if (filter === 'all') return 'all';
        if (filter === 'unlabeled') return 'Unlabeled';
        const label = this.labelsStorage.labels().find((l) => l.id === filter);
        return label && label.parent ? label.full_path : label?.name;
    });

    public ngOnInit(): void {
        // Clear selection whenever the active tab changes (Custom <-> MCP).
        let prevTab = this.currentTab();
        this.router.events
            .pipe(
                filter((e): e is NavigationEnd => e instanceof NavigationEnd),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => {
                const nextTab = this.currentTab();
                if (nextTab !== prevTab) {
                    this.viewState.setSelectMode(false);
                    this.viewState.clearSelection();
                    prevTab = nextTab;
                }
            });
    }

    public ngOnDestroy(): void {
        this.cancelBulkCloseTimeout();
        this.toolsSearchService.clearSearch();
        this.viewState.setSelectMode(false);
        this.viewState.clearSelection();
        this.viewState.resetFilter();
    }

    private currentTab(): 'custom' | 'mcp' | null {
        const url = this.router.url;
        if (url.includes('/mcp')) return 'mcp';
        if (url.includes('/custom')) return 'custom';
        return null;
    }

    public onSearchTermChange(term: string): void {
        this.searchTerm = term;
        this.toolsSearchService.setSearchTerm(term);
    }

    public clearSearch(): void {
        this.searchTerm = '';
        this.toolsSearchService.clearSearch();
    }

    public toggleSidebar(): void {
        this.showSidebar.update((v) => !v);
    }

    public selectAllLabels(): void {
        this.labelsStorage.setActiveLabelFilter('all');
    }

    public toggleFilterMenu(): void {
        this.filterMenuOpen.update((v) => !v);
    }

    public closeFilterMenu(): void {
        this.filterMenuOpen.set(false);
    }

    public onFilterMenuAction(action: ToolsFilterMenuAction): void {
        this.closeFilterMenu();
        switch (action) {
            case 'show_favorite':
                this.viewState.patchFilter({ showFavoriteOnly: !this.viewState.filter().showFavoriteOnly });
                return;
            case 'sort_asc':
                this.viewState.patchFilter({ sortOrder: 'name_asc' });
                return;
            case 'sort_desc':
                this.viewState.patchFilter({ sortOrder: 'name_desc' });
                return;
            case 'used_in_agent_surface':
                this.viewState.patchFilter({ sortOrder: 'used_in_agent_surface' });
                return;
            case 'used_in_shared_surface':
                this.viewState.patchFilter({ sortOrder: 'used_in_shared_surface' });
                return;
            case 'used_in_inline':
                this.viewState.patchFilter({ sortOrder: 'used_in_inline' });
                return;
            case 'most_used':
                this.viewState.patchFilter({ sortOrder: 'most_used' });
                return;
            case 'unused_first':
                this.viewState.patchFilter({ sortOrder: 'unused_first' });
                return;
            case 'include_exclude':
                // The active child list owns its tools; it opens the dialog.
                this.viewState.dispatch({ kind: 'open-include-exclude', initialTab: 'primary' });
                return;
            case 'custom_filter':
                this.openCustomFilterDialog();
                return;
        }
    }

    public clearAllFilters(): void {
        this.viewState.resetFilter();
    }

    private openCustomFilterDialog(): void {
        const data: AppCustomFilterDialogData = {
            scopes: [
                { key: 'tool_name', label: 'Tools', icon: 'tools', heading: 'Show tools matching the name conditions' },
                {
                    key: 'label_name',
                    label: 'Labels',
                    icon: 'label',
                    heading: 'Show tools matching the label conditions',
                },
            ],
            initialCondition: this.viewState.filter().customFilter,
        };
        const ref = this.dialog.open<AppCustomFilterDialogResult | undefined>(AppCustomFilterDialogComponent, {
            data,
            panelClass: 'tools-filter-dialog-panel',
            hasBackdrop: true,
        });
        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (!result) return;
            this.viewState.patchFilter({
                customFilter: result.condition as ReturnType<typeof this.viewState.filter>['customFilter'],
            });
        });
    }

    /** Clears the tool selection when the user clicks anywhere on the page
     *  that isn't a tool card or one of the explicitly whitelisted controls
     *  (marked with `data-selection-safe`). CDK overlays live outside this
     *  root so their clicks never reach this handler. */
    public onPageClick(event: MouseEvent): void {
        if (this.viewState.selectedCount() === 0) return;
        const target = event.target as HTMLElement | null;
        if (target?.closest('[data-selection-safe]')) return;
        this.viewState.clearSelection();
    }

    @HostListener('document:keydown.escape')
    public onEscape(): void {
        if (this.viewState.selectedCount() === 0) return;
        this.viewState.clearSelection();
    }

    public toggleBulkMenu(): void {
        const next = !this.bulkMenuOpen();
        this.bulkMenuOpen.set(next);
        if (next) {
            this.cancelBulkCloseTimeout();
            this.isMouseOnBulkButton.set(true);
            this.isMouseOnBulkMenu.set(false);
        }
    }

    public closeBulkMenu(): void {
        this.cancelBulkCloseTimeout();
        this.bulkMenuOpen.set(false);
        this.isMouseOnBulkButton.set(false);
        this.isMouseOnBulkMenu.set(false);
    }

    public onBulkButtonEnter(): void {
        this.isMouseOnBulkButton.set(true);
        this.cancelBulkCloseTimeout();
    }

    public onBulkButtonLeave(): void {
        this.isMouseOnBulkButton.set(false);
        this.scheduleBulkClose();
    }

    public onBulkMenuEnter(): void {
        this.isMouseOnBulkMenu.set(true);
        this.cancelBulkCloseTimeout();
    }

    public onBulkMenuLeave(): void {
        this.isMouseOnBulkMenu.set(false);
        this.scheduleBulkClose();
    }

    public onBulkOverlayOutsideClick(): void {
        if (this.isBulkLabelsOpen()) return;
        this.closeBulkMenu();
    }

    public onBulkLabelsOpenChange(open: boolean): void {
        this.isBulkLabelsOpen.set(open);
        if (open) {
            this.cancelBulkCloseTimeout();
        } else {
            this.scheduleBulkClose();
        }
    }

    private scheduleBulkClose(): void {
        if (this.isBulkLabelsOpen()) return;
        if (this.bulkMenuOpen() && !this.isMouseOnBulkButton() && !this.isMouseOnBulkMenu()) {
            this.bulkCloseTimeout = setTimeout(() => {
                if (
                    !this.isBulkLabelsOpen() &&
                    this.bulkMenuOpen() &&
                    !this.isMouseOnBulkButton() &&
                    !this.isMouseOnBulkMenu()
                ) {
                    this.closeBulkMenu();
                }
            }, 100);
        }
    }

    private cancelBulkCloseTimeout(): void {
        if (this.bulkCloseTimeout) {
            clearTimeout(this.bulkCloseTimeout);
            this.bulkCloseTimeout = null;
        }
    }

    public onBulkAction(action: ToolsBulkAction): void {
        this.closeBulkMenu();
        this.viewState.dispatch({ kind: action.kind });
    }

    public onBulkLabelsApplied(change: { addLabelIds: number[]; removeLabelIds: number[] }): void {
        this.closeBulkMenu();
        if (change.addLabelIds.length === 0 && change.removeLabelIds.length === 0) return;
        this.viewState.dispatch({
            kind: 'manage-labels',
            addLabelIds: change.addLabelIds,
            removeLabelIds: change.removeLabelIds,
        });
    }

    public onCreateToolClick(): void {
        this.viewState.dispatch({ kind: 'open-create' });
    }

    public onImportClick(): void {
        this.viewState.dispatch({ kind: 'open-import' });
    }

    public onExportClick(): void {
        this.viewState.setSelectMode(true);
    }

    public cancelExport(): void {
        this.viewState.setSelectMode(false);
    }

    public confirmExport(): void {
        if (this.viewState.selectedCount() === 0) return;
        this.viewState.dispatch({ kind: 'export-selected' });
        this.viewState.setSelectMode(false);
    }

    public toggleSelectAllTools(): void {
        this.viewState.toggleSelectAllVisible();
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
