import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    ActionDropdownButtonComponent,
    ActionDropdownItem,
    AppSvgIconComponent,
    NumberStepperComponent,
} from '@shared/components';
import { HasPermissionDirective, ResizableSidebarDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { SidebarWidthOptions, SidebarWidthService } from '@shared/services';
import { downloadBlob } from '@shared/utils';
import { debounceTime, finalize, Subject, Subscription } from 'rxjs';

import { ExportFormat } from '../../core/services/import-export.service';
import { ToastService } from '../../services/notifications';
import { AuditFilterChipsComponent } from './components/audit-filter-chips/audit-filter-chips.component';
import { AuditFiltersPanelComponent } from './components/audit-filters-panel/audit-filters-panel.component';
import { AuditHighlightComponent } from './components/audit-highlight/audit-highlight.component';
import { AuditValueViewerComponent } from './components/audit-value-viewer/audit-value-viewer.component';
import { AUDIT_FIELD_CATALOG } from './models/audit-domain.models';
import { AuditFilterState, EMPTY_AUDIT_FILTER } from './models/audit-filter.models';
import { AuditUserAction, UserActionSearchRequest, UserActionSearchResponse } from './models/audit-user-action.models';
import { USER_ACTION_FIELD_CATALOG } from './models/audit-user-action-filter-options';
import { AuditJsonPipe } from './pipes/audit-json.pipe';
import { AuditApiService } from './services/audit-api.service';
import { buildTimeZoneLabel } from './utils/audit-time-zone-label.util';
import { compileAuditFilter } from './utils/compile-audit-filter.util';
import { clearAuditFilterField, describeAuditFilter } from './utils/describe-audit-filter.util';
import { describeUserAction } from './utils/describe-user-action.util';

const DEFAULT_PAGE_SIZE = 20;
const MIN_PAGE_SIZE = 10;
const MAX_PAGE_SIZE = 100;
const PAGE_SIZE_STEP = 10;
const SEARCH_DEBOUNCE_MS = 400;
// the same side panel width as the Sessions tab, so switching tabs keeps it
const PANEL_WIDTH_KEY = 'audit-side-panel';
const PANEL_WIDTH_OPTIONS = { defaultWidth: 480, minWidth: 360, maxWidth: 960 } satisfies SidebarWidthOptions;

interface UserActionRow {
    event: AuditUserAction;
    description: string;
}

@Component({
    selector: 'app-audit-user-actions-browser',
    imports: [
        AppSvgIconComponent,
        ActionDropdownButtonComponent,
        AuditFilterChipsComponent,
        AuditFiltersPanelComponent,
        AuditHighlightComponent,
        AuditJsonPipe,
        AuditValueViewerComponent,
        DatePipe,
        HasPermissionDirective,
        NumberStepperComponent,
        ResizableSidebarDirective,
    ],
    providers: [{ provide: AUDIT_FIELD_CATALOG, useValue: USER_ACTION_FIELD_CATALOG }],
    templateUrl: './audit-user-actions-browser.component.html',
    // the toolbar, table, pager and side panel look the same as on the Sessions tab
    styleUrls: ['./audit-sessions-browser.component.scss', './audit-user-actions-browser.component.scss'],
})
export class AuditUserActionsBrowserComponent implements OnInit {
    protected readonly isLoading = signal(false);
    protected readonly loadError = signal(false);
    protected readonly loadErrorMessage = signal<string | null>(null);
    protected readonly isPartial = signal(false);
    protected readonly pageSize = signal(DEFAULT_PAGE_SIZE);
    protected readonly isFiltersPanelOpen = signal(false);
    protected readonly viewedRow = signal<UserActionRow | null>(null);
    protected readonly draftFilter = signal<AuditFilterState>(EMPTY_AUDIT_FILTER);
    protected readonly exportingFormat = signal<ExportFormat | null>(null);
    private readonly events = signal<AuditUserAction[]>([]);
    private readonly cursorStack = signal<(string | null)[]>([null]);
    private readonly nextCursor = signal<string | null>(null);
    private readonly appliedFilter = signal<AuditFilterState>(EMPTY_AUDIT_FILTER);

    protected readonly rows = computed<UserActionRow[]>(() =>
        this.events().map((event) => ({ event, description: describeUserAction(event) }))
    );
    protected readonly appliedChips = computed(() => describeAuditFilter(this.appliedFilter(), this.catalog));
    protected readonly appliedSearchText = computed(() => this.appliedFilter().searchText);
    protected readonly highlightTerm = computed(() => this.appliedSearchText().trim());
    protected readonly queryError = computed(() =>
        this.appliedFilter().mode === 'query' ? this.loadErrorMessage() : null
    );
    protected readonly canGoNewer = computed(() => this.cursorStack().length > 1);
    protected readonly canGoOlder = computed(() => this.nextCursor() !== null);
    protected readonly exportLabel = computed(() => {
        const format = this.exportingFormat();
        return format ? `Generating ${format.toUpperCase()}...` : 'Export';
    });

    protected readonly timeZoneLabel = buildTimeZoneLabel();
    protected readonly exportItems: ActionDropdownItem[] = [
        { label: 'Export as JSON', value: 'json' },
        { label: 'Export as CSV', value: 'csv' },
    ];
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
    protected readonly minPageSize = MIN_PAGE_SIZE;
    protected readonly maxPageSize = MAX_PAGE_SIZE;
    protected readonly pageSizeStep = PAGE_SIZE_STEP;
    protected readonly panelWidthKey = PANEL_WIDTH_KEY;
    protected readonly panelWidthOptions = PANEL_WIDTH_OPTIONS;
    protected readonly panelWidth = inject(SidebarWidthService).getWidth(PANEL_WIDTH_KEY, PANEL_WIDTH_OPTIONS);

    private readonly catalog = inject(AUDIT_FIELD_CATALOG);
    private readonly auditApiService = inject(AuditApiService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly searchInput = new Subject<string>();
    private searchSubscription: Subscription | null = null;
    private valueViewerTrigger: HTMLElement | null = null;

    public ngOnInit(): void {
        this.loadActions();
        this.searchInput
            .pipe(debounceTime(SEARCH_DEBOUNCE_MS), takeUntilDestroyed(this.destroyRef))
            .subscribe((text) => this.applySearch(text));
    }

    protected onSearchInput(text: string): void {
        this.searchInput.next(text);
    }

    protected applySearch(text: string): void {
        if (text.trim() === this.appliedFilter().searchText.trim()) {
            return;
        }
        const searchText = text.trim() === '' ? '' : text;
        this.draftFilter.update((state) => ({ ...state, searchText }));
        this.runFilter({ ...this.appliedFilter(), searchText });
    }

    // the stepper emits on every keystroke, so a half-typed or out-of-range number is ignored until it is valid
    protected setPageSize(size: number | null): void {
        if (size === null || size < MIN_PAGE_SIZE || size > MAX_PAGE_SIZE || size === this.pageSize()) {
            return;
        }
        this.pageSize.set(size);
        this.reloadFromFirstPage();
    }

    protected goToFirstPage(): void {
        if (this.canGoNewer()) {
            this.reloadFromFirstPage();
        }
    }

    protected goToNewerPage(): void {
        if (this.canGoNewer()) {
            this.cursorStack.update((stack) => stack.slice(0, -1));
            this.loadActions();
        }
    }

    protected goToOlderPage(): void {
        const cursor = this.nextCursor();
        if (cursor !== null) {
            this.cursorStack.update((stack) => [...stack, cursor]);
            this.loadActions();
        }
    }

    protected toggleFiltersPanel(): void {
        if (this.viewedRow()) {
            this.viewedRow.set(null);
            this.valueViewerTrigger = null;
            this.isFiltersPanelOpen.set(true);
            return;
        }
        this.isFiltersPanelOpen.update((isOpen) => !isOpen);
    }

    protected closeFiltersPanel(): void {
        this.draftFilter.set(this.appliedFilter());
        this.isFiltersPanelOpen.set(false);
    }

    protected applyFilters(state: AuditFilterState = this.draftFilter()): void {
        this.draftFilter.set(state);
        this.isFiltersPanelOpen.set(false);
        this.runFilter(state);
    }

    protected removeFilter(key: string): void {
        const next = clearAuditFilterField(this.appliedFilter(), key);
        this.draftFilter.set(next);
        this.runFilter(next);
    }

    protected clearFilters(): void {
        this.draftFilter.set(EMPTY_AUDIT_FILTER);
        this.runFilter(EMPTY_AUDIT_FILTER);
    }

    protected exportFiltered(format: ExportFormat): void {
        const { filters, query } = compileAuditFilter(this.appliedFilter(), this.catalog);
        this.exportingFormat.set(format);

        this.auditApiService
            .downloadExport('user_actions', { format, filters, query })
            .pipe(
                finalize(() => this.exportingFormat.set(null)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (response) => {
                    if (response.body) {
                        downloadBlob(response.body, `audit_user_actions_export_${Date.now()}.${format}`);
                    }
                },
                error: () => this.toastService.error('Failed to export user actions'),
            });
    }

    protected onExportItemSelected(item: ActionDropdownItem): void {
        this.exportFiltered(item.value as ExportFormat);
    }

    protected openRow(trigger: HTMLElement, row: UserActionRow): void {
        this.valueViewerTrigger = trigger;
        this.viewedRow.set(row);
    }

    // the panel is not a dialog, so focus is handed back to the cell by hand instead of falling to <body>
    protected closeValueViewer(): void {
        this.viewedRow.set(null);
        this.valueViewerTrigger?.focus();
        this.valueViewerTrigger = null;
    }

    private runFilter(state: AuditFilterState): void {
        this.appliedFilter.set(state);
        this.reloadFromFirstPage();
    }

    private reloadFromFirstPage(): void {
        this.cursorStack.set([null]);
        this.loadActions();
    }

    private loadActions(): void {
        this.searchSubscription?.unsubscribe();
        const stack = this.cursorStack();
        const { filters, query } = compileAuditFilter(this.appliedFilter(), this.catalog);
        this.isLoading.set(true);
        this.loadError.set(false);
        this.loadErrorMessage.set(null);

        this.searchSubscription = this.auditApiService
            .search<UserActionSearchRequest, UserActionSearchResponse>('user_actions', {
                filters,
                query,
                cursor: stack[stack.length - 1],
                size: this.pageSize(),
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    this.events.set(response.items);
                    this.nextCursor.set(response.next_cursor);
                    this.isPartial.set(response.partial);
                    this.isLoading.set(false);
                },
                error: (error: HttpErrorResponse) => {
                    const detail = error.error?.detail;
                    this.loadErrorMessage.set(error.status === 400 && typeof detail === 'string' ? detail : null);
                    this.events.set([]);
                    this.nextCursor.set(null);
                    this.isPartial.set(false);
                    this.loadError.set(true);
                    this.isLoading.set(false);
                },
            });
    }
}
