import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    DestroyRef,
    effect,
    ElementRef,
    Inject,
    inject,
    OnDestroy,
    OnInit,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import {
    ActionDropdownButtonComponent,
    ActionDropdownItem,
    IconButtonComponent,
    PaginationControlsComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { catchError, EMPTY, finalize, interval, map, merge, Subject, switchMap, takeUntil } from 'rxjs';
import { NodeGroup } from 'src/app/shared/models/node-group.model';

import { ExportFormat, ImportExportService } from '../../../../core/services/import-export.service';
import { ToastService } from '../../../../services/notifications/toast.service';
import { downloadBlob } from '../../../../shared/utils/download-blob.util';
import { GraphDto } from '../../models/graph.model';
import {
    GraphSessionLight,
    GraphSessionService,
    GraphSessionStatus,
    isTerminalSessionStatus,
} from '../../services/flows-sessions.service';
import { FlowSessionNodeFilterDropdownComponent } from './flow-session-node-filter-dropdown.component';
import { FlowSessionsTableComponent } from './flow-sessions-table.component';

@Component({
    selector: 'app-flow-sessions-list',
    templateUrl: './flow-sessions-list.component.html',
    styleUrls: ['./flow-sessions-list.component.scss'],
    standalone: true,
    imports: [
        CommonModule,
        FlowSessionsTableComponent,
        PaginationControlsComponent,
        FlowSessionNodeFilterDropdownComponent,
        IconButtonComponent,
        ActionDropdownButtonComponent,
        SelectComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowSessionsListComponent implements OnInit, OnDestroy {
    public flow!: GraphDto;
    public sessions = signal<GraphSessionLight[]>([]);
    public isLoaded = signal<boolean>(false);
    public currentPage = signal(1);
    public pageSize = signal(10);
    public readonly pageSizeItems: SelectItem[] = [
        { name: '10', value: 10 },
        { name: '20', value: 20 },
        { name: '50', value: 50 },
    ];
    public statusFilter = signal<string[]>(['all']);
    public nodeFilter = signal<string | null>(null);
    public totalCount = 0;
    public availableNodes = signal<string[]>([]);
    public isErrorCauseFilter = signal<boolean>(false);
    private reloadTrigger = signal(0);
    public availableNodeGroups = signal<NodeGroup[]>([]);
    public selectedIds = signal<Set<number>>(new Set());
    public isExporting = signal(false);
    public isDeleting = signal(false);
    private cancelLoad$ = new Subject<void>();
    private readonly destroyRef = inject(DestroyRef);
    private readonly importExportService = inject(ImportExportService);
    private readonly toastService = inject(ToastService);

    readonly exportItems: ActionDropdownItem[] = [
        { label: 'Export as JSON', value: 'json' },
        { label: 'Export as CSV', value: 'csv' },
    ];
    private cancelPolling$ = new Subject<void>();
    private destroy$ = new Subject<void>();
    private pendingIds = new Set<number>();
    private static readonly POLL_INTERVAL_MS = 5000;

    @ViewChild('sessionSearchInput')
    sessionSearchInput!: ElementRef<HTMLInputElement>;

    constructor(
        private graphSessionService: GraphSessionService,
        @Inject(DIALOG_DATA) public data: { flow: GraphDto },
        private router: Router,
        public dialogRef: DialogRef<unknown>,
        private cdr: ChangeDetectorRef
    ) {
        this.flow = data.flow;
        this.loadAvailableNodes();
        effect(() => {
            const page = this.currentPage();
            const size = this.pageSize();
            const status = this.statusFilter();
            const nodeName = this.nodeFilter();
            const isErrorCause = this.isErrorCauseFilter();
            this.reloadTrigger();
            this.loadSessions(size, (page - 1) * size, status, nodeName, isErrorCause);
        });
    }

    public ngOnInit(): void {
        this.currentPage.set(1);
    }

    private loadAvailableNodes(): void {
        const groups: NodeGroup[] = [
            {
                label: 'Crew Node',
                icon: 'ti ti-users',
                color: '#f0a500',
                nodes: this.extractNodeNames(this.flow?.crew_node_list),
            },
            {
                label: 'Python Node',
                icon: 'ti ti-brand-python',
                color: '#ffcf3f',
                nodes: this.extractNodeNames(this.flow?.python_node_list),
            },
            {
                label: 'LLM Node',
                icon: 'ti ti-brain',
                color: '#a78bfa',
                nodes: this.extractNodeNames(this.flow?.llm_node_list),
            },
            {
                label: 'File Extractor',
                icon: 'ti ti-file-search',
                color: '#38bdf8',
                nodes: this.extractNodeNames(this.flow?.file_extractor_node_list),
            },
            {
                label: 'Audio to Text',
                icon: 'ti ti-microphone',
                color: '#f472b6',
                nodes: this.extractNodeNames(this.flow?.audio_transcription_node_list),
            },
            {
                label: 'Webhook Trigger',
                icon: 'ti ti-webhook',
                color: '#34d399',
                nodes: this.extractNodeNames(this.flow?.webhook_trigger_node_list),
            },
            {
                label: 'Telegram Trigger',
                icon: 'ti ti-brand-telegram',
                color: '#38bdf8',
                nodes: this.extractNodeNames(this.flow?.telegram_trigger_node_list),
            },
            {
                label: 'Subgraph',
                icon: 'ti ti-hierarchy',
                color: '#fb923c',
                nodes: this.extractNodeNames(this.flow?.subgraph_node_list),
            },
            {
                label: 'Code Agent',
                icon: 'ti ti-robot',
                color: '#4ade80',
                nodes: this.extractNodeNames(this.flow?.code_agent_node_list),
            },
            {
                label: 'End',
                icon: 'ti ti-square-rounded',
                color: '#d3d3d3',
                nodes: this.extractNodeNames(this.flow?.end_node_list),
            },
        ].filter((g) => g.nodes.length > 0);

        this.availableNodeGroups.set(groups);

        const allNodes = groups.flatMap((g) => g.nodes);
        this.availableNodes.set(allNodes);
    }

    private extractNodeNames(list: { node_name?: string; id: number }[] | undefined | null): string[] {
        if (!list?.length) return [];
        return list
            .filter((n) => n?.node_name)
            .map((n) => `${n.node_name} #${n.id}`)
            .filter(Boolean)
            .sort();
    }

    public onIsErrorCauseChange(): void {
        this.isErrorCauseFilter.set(!this.isErrorCauseFilter());
        this.currentPage.set(1);
    }

    private loadSessions(
        limit: number,
        offset: number,
        status: string[],
        nodeName: string | null = null,
        isErrorCause: boolean = false
    ): void {
        this.cancelLoad$.next();
        this.cancelPolling$.next();
        this.pendingIds.clear();
        this.isLoaded.set(false);
        if (this.flow && this.flow.id) {
            this.graphSessionService
                .getSessionsByGraphId(this.flow.id, false, limit, offset, status, nodeName, isErrorCause)
                .pipe(takeUntil(this.cancelLoad$))
                .subscribe({
                    next: (sessions) => {
                        this.sessions.set(sessions.results);
                        this.isLoaded.set(true);
                        this.totalCount = sessions.count;
                        this.cdr.markForCheck();
                        this.startStatusPolling();
                    },
                    error: () => {
                        this.totalCount = 0;
                        this.sessions.set([]);
                        this.isLoaded.set(true);
                        this.pageSize.set(10);
                        this.currentPage.set(1);
                    },
                });
        } else {
            this.isLoaded.set(true);
        }
    }

    private startStatusPolling(): void {
        this.pendingIds = new Set(
            this.sessions()
                .filter((s) => !isTerminalSessionStatus(s.status))
                .map((s) => s.id)
        );
        if (this.pendingIds.size === 0) return;

        interval(FlowSessionsListComponent.POLL_INTERVAL_MS)
            .pipe(
                switchMap(() => {
                    const ids = Array.from(this.pendingIds);
                    if (ids.length === 0) {
                        this.cancelPolling$.next();
                        return EMPTY;
                    }
                    return merge(
                        ...ids.map((id) =>
                            this.graphSessionService.getSessionUpdates(String(id)).pipe(
                                map((update) => ({ id, status: update.status })),
                                catchError(() => EMPTY)
                            )
                        )
                    );
                }),
                takeUntil(this.cancelPolling$)
            )
            .subscribe(({ id, status }) => this.handleStatusUpdate(id, status));
    }

    private handleStatusUpdate(id: number, status: GraphSessionStatus): void {
        const currentSession = this.sessions().find((s) => s.id === id);
        if (!currentSession) {
            this.pendingIds.delete(id);
            return;
        }
        if (isTerminalSessionStatus(currentSession.status)) {
            this.pendingIds.delete(id);
            return;
        }
        if (currentSession.status === status) return;

        this.sessions.update((sessions) => sessions.map((s) => (s.id === id ? { ...s, status } : s)));

        if (isTerminalSessionStatus(status)) {
            this.pendingIds.delete(id);
            this.graphSessionService
                .getSessionById(id)
                .pipe(
                    takeUntil(this.destroy$),
                    catchError(() => EMPTY)
                )
                .subscribe((fullSession) => {
                    this.sessions.update((sessions) =>
                        sessions.map((s) =>
                            s.id === id ? { ...s, status: fullSession.status, finished_at: fullSession.finished_at } : s
                        )
                    );
                });
            if (this.pendingIds.size === 0) {
                this.cancelPolling$.next();
            }
        }
    }

    public onDeleteSelected(ids: number[]): void {
        if (ids.length === 0) return;

        this.isDeleting.set(true);
        this.graphSessionService
            .bulkDeleteSessions(ids)
            .pipe(
                finalize(() => this.isDeleting.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.selectedIds.update((prev) => {
                        const next = new Set(prev);
                        ids.forEach((id) => next.delete(id));
                        return next;
                    });
                    this.reloadAfterDeletion(ids);
                },
                error: (err) => {
                    console.error('Failed to bulk delete sessions', err);
                },
            });
    }

    private reloadAfterDeletion(deletedIds: number[]): void {
        const currentSessions = this.sessions();
        const remainingSessionsOnPage = currentSessions.filter((session) => !deletedIds.includes(session.id));
        const currentPageNumber = this.currentPage();

        if (remainingSessionsOnPage.length === 0 && currentPageNumber > 1) {
            this.currentPage.set(currentPageNumber - 1);
        } else {
            this.reloadTrigger.update((val) => val + 1);
        }
    }

    public onViewSession(sessionId: number): void {
        this.router.navigate(['/graph', this.flow.id, 'session', sessionId]);
        this.dialogRef.close();
    }

    public onStopSession(sessionId: number): void {
        this.graphSessionService.stopSessionById(sessionId).subscribe({
            next: () => {
                this.sessions.update((sessions) =>
                    sessions.map((s) =>
                        s.id === sessionId
                            ? { ...s, status: GraphSessionStatus.STOP, finished_at: new Date().toISOString() }
                            : s
                    )
                );
                this.pendingIds.delete(sessionId);
                if (this.pendingIds.size === 0) {
                    this.cancelPolling$.next();
                }
            },
            error: (err) => {
                console.error('Failed to stop session', err);
            },
        });
    }

    onPageChange(page: number) {
        this.currentPage.set(page);
    }

    onPageSizeChange(size: number) {
        this.pageSize.set(size);
        this.currentPage.set(1);
    }

    onStatusFilterChange(values: string[]) {
        this.currentPage.set(1);
        this.statusFilter.set(values);
    }

    public ngOnDestroy() {
        this.destroy$.next();
        this.destroy$.complete();
        this.cancelLoad$.complete();
        this.cancelPolling$.next();
        this.cancelPolling$.complete();
        this.pendingIds.clear();
        this.sessions.set([]);
    }

    onNodeFilterChange(value: string | null) {
        this.currentPage.set(1);
        this.nodeFilter.set(value);
        if (!value) {
            this.isErrorCauseFilter.set(false);
        }
    }

    public onSelectedIdsChange(ids: Set<number>): void {
        this.selectedIds.set(ids);
    }

    public onBulkDelete(): void {
        this.onDeleteSelected(Array.from(this.selectedIds()));
    }

    public onExport(format: ExportFormat): void {
        if (this.selectedIds().size === 0 && this.totalCount === 0) {
            return;
        }
        this.isExporting.set(true);
        const activeStatuses = this.statusFilter().filter((s) => s !== 'all');
        const obs$ =
            this.selectedIds().size > 0
                ? this.importExportService.bulkExportSessions(Array.from(this.selectedIds()), format)
                : this.importExportService.exportAll(
                      {
                          graph: this.flow.id,
                          status: activeStatuses.length > 0 ? activeStatuses : undefined,
                          node_name: this.nodeFilter() ?? undefined,
                          is_error_cause: this.isErrorCauseFilter() || undefined,
                      },
                      format
                  );

        obs$.pipe(
            finalize(() => this.isExporting.set(false)),
            takeUntilDestroyed(this.destroyRef)
        ).subscribe({
            next: (blob) => {
                downloadBlob(blob, `sessions_export_${Date.now()}.${format}`);
                this.toastService.success('Sessions exported successfully');
            },
            error: () => {
                this.toastService.error('Failed to export sessions');
            },
        });
    }

    public onExportItemSelected(item: ActionDropdownItem): void {
        this.onExport(item.value as ExportFormat);
    }
}
