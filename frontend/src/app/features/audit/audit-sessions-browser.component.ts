import { Dialog } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    DOCUMENT,
    effect,
    inject,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActionDropdownButtonComponent, ActionDropdownItem, AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { downloadBlob } from '@shared/utils';
import {
    catchError,
    debounceTime,
    exhaustMap,
    filter,
    finalize,
    first,
    forkJoin,
    fromEvent,
    interval,
    merge,
    of,
    Subject,
    Subscription,
    switchMap,
    timeout,
    timer,
} from 'rxjs';

import { ExportFormat } from '../../core/services/import-export.service';
import { ActiveOrgService } from '../../services/auth/active-org.service';
import { ToastService } from '../../services/notifications';
import { AgentDefinitionsApiService } from '../agent-definitions/services/agent-definitions-api.service';
import { FlowsApiService } from '../flows/services/flows-api.service';
import { CustomToolsService } from '../tools/services/custom-tools/custom-tools.service';
import { McpToolsService } from '../tools/services/mcp-tools/mcp-tools.service';
import { AuditFilterChipsComponent } from './components/audit-filter-chips/audit-filter-chips.component';
import { AuditFiltersPanelComponent } from './components/audit-filters-panel/audit-filters-panel.component';
import { AuditHighlightComponent } from './components/audit-highlight/audit-highlight.component';
import {
    AuditValueDialogComponent,
    AuditValueDialogData,
} from './components/audit-value-dialog/audit-value-dialog.component';
import { AuditEnumOption, AuditFilterState, EMPTY_AUDIT_FILTER } from './models/audit-filter.models';
import { AuditExportRequest, AuditSessionEvent } from './models/audit-session.models';
import { AuditJsonPipe } from './pipes/audit-json.pipe';
import { AuditApiService } from './services/audit-api.service';
import {
    auditFilterStorageKey,
    readStoredAuditFilter,
    writeStoredAuditFilter,
} from './utils/audit-filter-storage.util';
import { AuditRow, buildAuditRows } from './utils/build-audit-rows.util';
import { compileAuditFilter } from './utils/compile-audit-filter.util';
import { clearAuditFilterField, describeAuditFilter } from './utils/describe-audit-filter.util';
import { sanitizeToolName } from './utils/sanitize-tool-name.util';

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const POLL_INTERVAL_MS = 10_000;
const SEARCH_DEBOUNCE_MS = 400;
const EXPORT_POLL_INTERVAL_MS = 1_000;
const EXPORT_TIMEOUT_MS = 5 * 60_000;

@Component({
    selector: 'app-audit-sessions-browser',
    standalone: true,
    imports: [
        CommonModule,
        AppSvgIconComponent,
        AuditFiltersPanelComponent,
        AuditFilterChipsComponent,
        AuditHighlightComponent,
        AuditJsonPipe,
        ActionDropdownButtonComponent,
        HasPermissionDirective,
    ],
    templateUrl: './audit-sessions-browser.component.html',
    styleUrls: ['./audit-sessions-browser.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditSessionsBrowserComponent implements OnInit {
    private auditApiService = inject(AuditApiService);
    private flowApiService = inject(FlowsApiService);
    private agentService = inject(AgentDefinitionsApiService);
    private customToolsService = inject(CustomToolsService);
    private mcpToolsService = inject(McpToolsService);
    private destroyRef = inject(DestroyRef);
    private document = inject(DOCUMENT);
    private toastService = inject(ToastService);
    private dialog = inject(Dialog);
    // Read once: an org switch remounts this page, so a later org change must not redirect writes.
    private readonly activeOrgId = inject(ActiveOrgService).activeOrgId();
    private readonly appliedFilterStorageKey = auditFilterStorageKey(this.activeOrgId, 'applied');
    private readonly draftFilterStorageKey = auditFilterStorageKey(this.activeOrgId, 'draft');
    private searchSubscription: Subscription | null = null;
    private searchInput = new Subject<string>();
    public readonly timeZoneLabel = buildTimeZoneLabel();

    public isLoading = signal<boolean>(false);
    public loadError = signal<boolean>(false);
    public loadErrorMessage = signal<string | null>(null);
    public isPartial = signal<boolean>(false);
    public pageSize = signal<number>(20);
    public areColumnsExpanded = signal<boolean>(false);
    public isFiltersPanelOpen = signal<boolean>(false);
    private rawEvents = signal<AuditSessionEvent[]>([]);
    private cursorStack = signal<(string | null)[]>([null]);
    private nextCursor = signal<string | null>(null);
    private appliedFilter = signal<AuditFilterState>(readStoredAuditFilter(this.appliedFilterStorageKey));
    // a selection made in the panel but not applied yet also survives a reload
    protected draftFilter = signal<AuditFilterState>(
        readStoredAuditFilter(this.draftFilterStorageKey, this.appliedFilter())
    );
    private collapsedIds = signal<ReadonlySet<string>>(new Set());
    private readonly persistAppliedFilter = effect(() =>
        writeStoredAuditFilter(this.appliedFilterStorageKey, this.appliedFilter())
    );
    private readonly persistDraftFilter = effect(() =>
        writeStoredAuditFilter(this.draftFilterStorageKey, this.draftFilter())
    );
    public flowNames = signal<string[]>([]);
    public exportingFormat = signal<ExportFormat | null>(null);
    public allRows = computed(() => buildAuditRows(this.rawEvents()));
    public isRowCollapsed(id: string): boolean {
        return this.collapsedIds().has(id);
    }
    protected exportLabel = computed(() => {
        const format = this.exportingFormat();
        return format ? `Generating ${format.toUpperCase()}...` : 'Export';
    });
    protected readonly exportItems: ActionDropdownItem[] = [
        { label: 'Export as JSON', value: 'json' },
        { label: 'Export as CSV', value: 'csv' },
    ];
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    public hasCollapsibleRows = computed(() => this.allRows().some((row) => row.hasChildren));
    public areAllRowsExpanded = computed(() => this.collapsedIds().size === 0);

    public toggleAllRows(): void {
        if (this.areAllRowsExpanded()) {
            this.collapsedIds.set(
                new Set(
                    this.allRows()
                        .filter((row) => row.hasChildren)
                        .map((row) => row.event.id)
                )
            );
            return;
        }
        this.collapsedIds.set(new Set());
    }

    public rows = computed(() => {
        const collapsed = this.collapsedIds();
        if (collapsed.size === 0) {
            return this.allRows();
        }
        return this.allRows().filter((row) => !row.parentIds.some((id) => collapsed.has(id)));
    });

    public appliedChips = computed(() =>
        describeAuditFilter(this.appliedFilter(), { agents: this.agentOptions(), tools: this.toolOptions() })
    );
    public activeFilterCount = computed(() => this.appliedChips().length);
    protected appliedSearchText = computed(() => this.appliedFilter().searchText);
    protected highlightTerm = computed(() => this.appliedSearchText().trim());
    public queryError = computed(() => (this.appliedFilter().mode === 'query' ? this.loadErrorMessage() : null));
    public canGoNewer = computed(() => this.cursorStack().length > 1);
    public canGoOlder = computed(() => this.nextCursor() !== null);

    public counts = computed(() => {
        const events = this.rawEvents();
        return {
            matches: events.filter((event) => event.filter_matched).length,
            rows: events.length,
            sessions: events.filter((event) => event.kind === 'session').length,
            nodes: events.filter((event) => event.kind === 'node').length,
            events: events.filter((event) => event.kind === 'event').length,
        };
    });

    public toggleRow(id: string): void {
        this.collapsedIds.update((current) => {
            const next = new Set(current);
            if (!next.delete(id)) {
                next.add(id);
            }
            return next;
        });
    }

    public canDecreasePageSize = computed(() => PAGE_SIZE_OPTIONS.indexOf(this.pageSize()) > 0);
    public canIncreasePageSize = computed(
        () => PAGE_SIZE_OPTIONS.indexOf(this.pageSize()) < PAGE_SIZE_OPTIONS.length - 1
    );

    public ngOnInit(): void {
        this.loadSessions();
        this.loadFlowNames();
        this.loadAgents();
        this.loadTools();
        this.startPolling();
        this.listenToSearchInput();
    }

    public onSearchInput(text: string): void {
        this.searchInput.next(text);
    }

    public applySearch(text: string): void {
        if (text.trim() === this.appliedFilter().searchText.trim()) {
            return;
        }
        const searchText = text.trim() === '' ? '' : text;
        this.appliedFilter.update((state) => ({ ...state, searchText }));
        this.draftFilter.update((state) => ({ ...state, searchText }));
        this.cursorStack.set([null]);
        this.loadSessions();
    }

    public stepPageSize(delta: number): void {
        const next = PAGE_SIZE_OPTIONS[PAGE_SIZE_OPTIONS.indexOf(this.pageSize()) + delta];
        if (next === undefined) {
            return;
        }
        this.pageSize.set(next);
        this.cursorStack.set([null]);
        this.loadSessions();
    }

    public goToFirstPage(): void {
        if (!this.canGoNewer()) {
            return;
        }
        this.cursorStack.set([null]);
        this.loadSessions();
    }

    public goToNewerPage(): void {
        if (!this.canGoNewer()) {
            return;
        }
        this.cursorStack.update((stack) => stack.slice(0, -1));
        this.loadSessions();
    }

    public goToOlderPage(): void {
        const cursor = this.nextCursor();
        if (cursor === null) {
            return;
        }
        this.cursorStack.update((stack) => [...stack, cursor]);
        this.loadSessions();
    }

    public setColumnsExpanded(expanded: boolean): void {
        this.areColumnsExpanded.set(expanded);
    }

    public toggleFiltersPanel(): void {
        this.isFiltersPanelOpen.update((isOpen) => !isOpen);
    }

    public closeFiltersPanel(): void {
        this.draftFilter.set(this.appliedFilter());
        this.isFiltersPanelOpen.set(false);
    }

    public applyFilters(state: AuditFilterState = this.draftFilter()): void {
        this.draftFilter.set(state);
        this.appliedFilter.set(state);
        this.cursorStack.set([null]);
        this.isFiltersPanelOpen.set(false);
        this.loadSessions();
    }

    public removeFilter(key: string): void {
        const next = clearAuditFilterField(this.appliedFilter(), key);
        this.appliedFilter.set(next);
        this.draftFilter.set(next);
        this.cursorStack.set([null]);
        this.loadSessions();
    }

    public clearFilters(): void {
        this.draftFilter.set(EMPTY_AUDIT_FILTER);
        this.appliedFilter.set(EMPTY_AUDIT_FILTER);
        this.cursorStack.set([null]);
        this.loadSessions();
    }

    public loadSessions(silent = false): void {
        this.searchSubscription?.unsubscribe();
        const stack = this.cursorStack();
        const { filters, query, matchScope } = compileAuditFilter(this.appliedFilter());
        if (!silent) {
            this.isLoading.set(true);
            this.loadError.set(false);
            this.loadErrorMessage.set(null);
        }

        this.searchSubscription = this.auditApiService
            .searchSessions({
                filters,
                query,
                match_scope: matchScope,
                cursor: stack[stack.length - 1],
                size: this.pageSize(),
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    this.rawEvents.set(response.items);
                    this.nextCursor.set(response.next_cursor);
                    this.isPartial.set(response.partial);
                    if (silent) {
                        return;
                    }
                    this.isLoading.set(false);
                    this.collapsedIds.set(new Set());
                },
                error: (error: HttpErrorResponse) => {
                    if (silent) {
                        return;
                    }
                    const detail = error.error?.detail;
                    this.loadErrorMessage.set(error.status === 400 && typeof detail === 'string' ? detail : null);
                    this.rawEvents.set([]);
                    this.nextCursor.set(null);
                    this.isPartial.set(false);
                    this.loadError.set(true);
                    this.isLoading.set(false);
                },
            });
    }

    public loadFlowNames(): void {
        this.flowApiService
            .getGraphsLight()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (flows) => {
                    const uniqueNames = new Set(flows.map((flow) => flow.name));
                    const sortedNames = Array.from(uniqueNames).sort((a, b) => a.localeCompare(b));
                    this.flowNames.set(sortedNames);
                },
                error: () => {
                    this.flowNames.set([]);
                },
            });
    }

    public agentOptions = signal<AuditEnumOption[]>([]);
    public toolOptions = signal<AuditEnumOption[]>([]);

    public loadTools(): void {
        forkJoin({
            python: this.customToolsService.getPythonCodeTools().pipe(catchError(() => of([]))),
            mcp: this.mcpToolsService.getMcpTools().pipe(catchError(() => of([]))),
        })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: ({ python, mcp }) => {
                    const names = [...python.map((tool) => tool.name), ...mcp.map((tool) => tool.name)];
                    const byValue = new Map(names.map((name) => [sanitizeToolName(name), name]));
                    this.toolOptions.set(
                        Array.from(byValue, ([value, label]) => ({ value, label })).sort((a, b) =>
                            a.label.localeCompare(b.label)
                        )
                    );
                },
                error: () => this.toolOptions.set([]),
            });
    }

    public loadAgents(): void {
        this.agentService
            .getAgentDefinitions()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (agents) => {
                    this.agentOptions.set(agents.map((agent) => ({ value: String(agent.id), label: agent.name })));
                },
                error: () => this.agentOptions.set([]),
            });
    }

    private startPolling(): void {
        merge(interval(POLL_INTERVAL_MS), fromEvent(this.document, 'visibilitychange'))
            .pipe(
                filter(() => this.canRefreshSilently()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.loadSessions(true));
    }

    private listenToSearchInput(): void {
        this.searchInput
            .pipe(debounceTime(SEARCH_DEBOUNCE_MS), takeUntilDestroyed(this.destroyRef))
            .subscribe((text) => this.applySearch(text));
    }

    private canRefreshSilently(): boolean {
        return (
            this.cursorStack().length === 1 &&
            this.document.visibilityState === 'visible' &&
            !this.isLoading() &&
            !this.loadError() &&
            (this.searchSubscription?.closed ?? true)
        );
    }

    public exportFiltered(format: ExportFormat): void {
        const { filters, query, matchScope } = compileAuditFilter(this.appliedFilter());
        const request: AuditExportRequest = { format, filters, query, match_scope: matchScope };
        this.exportingFormat.set(format);

        this.auditApiService
            .startExport(request)
            .pipe(
                switchMap(({ job_id }) =>
                    timer(0, EXPORT_POLL_INTERVAL_MS).pipe(
                        exhaustMap(() => this.auditApiService.getExportFile(job_id)),
                        first((response) => response.status === 200)
                    )
                ),
                timeout({ first: EXPORT_TIMEOUT_MS }),
                finalize(() => this.exportingFormat.set(null)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (response) => {
                    if (response.body) {
                        downloadBlob(response.body, `audit_export_${Date.now()}.${format}`);
                    }
                },
                error: () => this.toastService.error('Failed to export audit records'),
            });
    }

    public onExportItemSelected(item: ActionDropdownItem): void {
        this.exportFiltered(item.value as ExportFormat);
    }

    protected openValue(field: string, row: AuditRow, value: string, isPlainText = false): void {
        const rowName = row.event.name || row.nameLabel;
        this.dialog.open<void, AuditValueDialogData>(AuditValueDialogComponent, {
            data: { title: rowName ? `${field} — ${rowName}` : field, value, isPlainText },
        });
    }
}

function buildTimeZoneLabel(): string {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const offsetMinutes = -new Date().getTimezoneOffset();
    const sign = offsetMinutes < 0 ? '-' : '+';
    const absolute = Math.abs(offsetMinutes);
    const hours = String(Math.floor(absolute / 60)).padStart(2, '0');
    const minutes = String(absolute % 60).padStart(2, '0');
    return `${sign}${hours}:${minutes} ${zone}`;
}
