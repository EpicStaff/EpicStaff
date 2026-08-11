import { Dialog } from '@angular/cdk/dialog';
import { OverlayModule } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, computed, inject, OnDestroy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import {
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
import { tap } from 'rxjs/operators';

import { HideInlineSubtitleOnOverflowDirective } from '../../../../shared/directives/hide-inline-subtitle-on-overflow.directive';
import { CreateCustomToolDialogComponent } from '../../../../user-settings-page/tools/custom-tool-editor/create-custom-tool-dialog/create-custom-tool-dialog.component';
import { McpToolDialogComponent } from '../../components/mcp-tool-dialog/mcp-tool-dialog.component';
import { GetMcpToolRequest } from '../../models/mcp-tool.model';
import { GetPythonCodeToolRequest } from '../../models/python-code-tool.model';
import { ToolsEventsService } from '../../services/tools-events.service';
import { ToolsLabelsStorageService } from '../../services/tools-labels-storage.service';
import { ToolsSearchService } from '../../services/tools-search.service';
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
export class ToolsListPageComponent implements OnDestroy {
    public tabs = [
        { label: 'Custom', link: 'custom' },
        { label: 'MCP', link: 'mcp' },
    ];

    public searchTerm: string = '';

    public showSidebar = signal<boolean>(true);
    public filterMenuOpen = signal<boolean>(false);
    public bulkMenuOpen = signal<boolean>(false);
    public showUsageAndUnused = signal<boolean>(false);

    // TODO: populate from card selection UI when it's wired up.
    public readonly selectedToolIds = signal<number[]>([]);

    private readonly noSelectionActions: ToolsBulkAction[] = [
        {
            label: 'Select All',
            action: () => {
                // TODO: wire select-all behavior once selection state is defined.
            },
        },
        {
            label: 'Delete All Unused',
            action: () => {
                // TODO: wire delete-all-unused once usage endpoint is available.
            },
        },
    ];

    // "Add Label" is rendered by the bulk-actions-menu itself (label-dropdown trigger),
    // not as a plain action here.
    private readonly selectionActions: ToolsBulkAction[] = [
        {
            label: 'Select All',
            action: () => {
                // TODO: wire select-all behavior once selection state is defined.
            },
        },
        {
            label: 'Make Favorite',
            action: () => {
                // TODO: wire bulk favorite once endpoint is available.
            },
        },
        {
            label: 'Duplicate',
            action: () => {
                // TODO: wire bulk duplicate once endpoint is available.
            },
        },
        {
            label: 'Delete All Selected',
            action: () => {
                // TODO: wire bulk delete once endpoint is available.
            },
        },
    ];

    public readonly hasSelection = computed(() => this.selectedToolIds().length > 0);

    public readonly bulkActions = computed<ToolsBulkAction[]>(() =>
        this.hasSelection() ? this.selectionActions : this.noSelectionActions
    );

    private readonly dialog = inject(Dialog);
    private readonly router = inject(Router);
    private readonly toolsEventsService = inject(ToolsEventsService);
    private readonly toolsSearchService = inject(ToolsSearchService);
    private readonly labelsStorage = inject(ToolsLabelsStorageService);

    public readonly activeLabelFilterDisplay = computed(() => {
        const filter = this.labelsStorage.activeLabelFilter();
        if (filter === 'all') return 'all';
        if (filter === 'unlabeled') return 'Unlabeled';
        const label = this.labelsStorage.labels().find((l) => l.id === filter);
        return label && label.parent ? label.full_path : label?.name;
    });

    public get isMcpTabActive(): boolean {
        return this.router.url.includes('/mcp');
    }

    public ngOnDestroy(): void {
        this.toolsSearchService.clearSearch();
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

    public onFilterMenuAction(_action: ToolsFilterMenuAction): void {
        void _action;
        // TODO: wire filter actions once tool filter state model is defined.
        this.closeFilterMenu();
    }

    public toggleBulkMenu(): void {
        this.bulkMenuOpen.update((v) => !v);
    }

    public closeBulkMenu(): void {
        this.bulkMenuOpen.set(false);
    }

    public onBulkAction(_action: ToolsBulkAction): void {
        void _action;
        // TODO: wire bulk actions once behavior is defined.
        this.closeBulkMenu();
    }

    public onBulkLabelsChanged(labelIds: number[]): void {
        this.closeBulkMenu();
        // TODO: PATCH each selected tool with union of existing labels and chosen labelIds
        // once a tools bulk-update endpoint is available.
        void labelIds;
    }

    public onCreateToolClick(): void {
        if (this.isMcpTabActive) {
            this.openMcpToolDialog();
        } else {
            this.openCustomToolDialog();
        }
    }

    public openCustomToolDialog(): void {
        const dialogRef = this.dialog.open<GetPythonCodeToolRequest>(CreateCustomToolDialogComponent);

        dialogRef.closed
            .pipe(
                tap((result) => {
                    if (result) {
                        this.toolsEventsService.emitCustomToolCreated(result);
                        this.router.navigate(['/tools/custom']);
                    }
                })
            )
            .subscribe();
    }

    public openMcpToolDialog(): void {
        const dialogRef = this.dialog.open<GetMcpToolRequest>(McpToolDialogComponent, {
            data: {},
            maxWidth: '95vw',
            maxHeight: '90vh',
            autoFocus: true,
        });

        dialogRef.closed
            .pipe(
                tap((result) => {
                    if (result) {
                        this.toolsEventsService.emitMcpToolCreated(result);
                        this.router.navigate(['/tools/mcp']);
                    }
                })
            )
            .subscribe();
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
