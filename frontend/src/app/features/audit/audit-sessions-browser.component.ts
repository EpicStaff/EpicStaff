import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent } from '@shared/components';
import { catchError, forkJoin, of } from 'rxjs';

import { AgentDefinitionsApiService } from '../agent-definitions/services/agent-definitions-api.service';
import { FlowsApiService } from '../flows/services/flows-api.service';
import { CustomToolsService } from '../tools/services/custom-tools/custom-tools.service';
import { McpToolsService } from '../tools/services/mcp-tools/mcp-tools.service';
import { AuditFilterChipsComponent } from './components/audit-filter-chips/audit-filter-chips.component';
import { AuditFiltersPanelComponent } from './components/audit-filters-panel/audit-filters-panel.component';
import { AuditEnumOption, AuditFilterState, EMPTY_AUDIT_FILTER } from './models/audit-filter.models';
import { AuditSessionEvent } from './models/audit-session.models';
import { AuditApiService } from './services/audit-api.service';
import { buildAuditRows } from './utils/build-audit-rows.util';
import { compileAuditFilter } from './utils/compile-audit-filter.util';
import { clearAuditFilterField, describeAuditFilter } from './utils/describe-audit-filter.util';
import { sanitizeToolName } from './utils/sanitize-tool-name.util';

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

@Component({
    selector: 'app-audit-sessions-browser',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent, AuditFiltersPanelComponent, AuditFilterChipsComponent],
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
    public readonly timeZoneLabel = buildTimeZoneLabel();

    public isLoading = signal<boolean>(false);
    public loadError = signal<boolean>(false);
    public isPartial = signal<boolean>(false);
    public pageSize = signal<number>(20);
    public areColumnsExpanded = signal<boolean>(false);
    public isFiltersPanelOpen = signal<boolean>(false);
    private rawEvents = signal<AuditSessionEvent[]>([]);
    private cursorStack = signal<(string | null)[]>([null]);
    private nextCursor = signal<string | null>(null);
    protected draftFilter = signal<AuditFilterState>(EMPTY_AUDIT_FILTER);
    private appliedFilter = signal<AuditFilterState>(EMPTY_AUDIT_FILTER);
    private collapsedIds = signal<ReadonlySet<string>>(new Set());
    public flowNames = signal<string[]>([]);
    public allRows = computed(() => buildAuditRows(this.rawEvents()));
    public isRowCollapsed(id: string): boolean {
        return this.collapsedIds().has(id);
    }

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
    public canGoNewer = computed(() => this.cursorStack().length > 1);
    public canGoOlder = computed(() => this.nextCursor() !== null);

    public counts = computed(() => {
        const events = this.rawEvents();
        return {
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

    public applyFilters(): void {
        this.appliedFilter.set(this.draftFilter());
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

    public loadSessions(): void {
        const stack = this.cursorStack();
        const { filters, matchScope } = compileAuditFilter(this.appliedFilter());
        this.isLoading.set(true);
        this.loadError.set(false);

        this.auditApiService
            .searchSessions({
                filters,
                match_scope: matchScope,
                cursor: stack[stack.length - 1],
                size: this.pageSize(),
            })
            .subscribe({
                next: (response) => {
                    this.rawEvents.set(response.items);
                    this.nextCursor.set(response.next_cursor);
                    this.isPartial.set(response.partial);
                    this.isLoading.set(false);
                    this.collapsedIds.set(new Set());
                },
                error: () => {
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
