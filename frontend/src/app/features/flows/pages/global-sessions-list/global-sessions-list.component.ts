import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    effect,
    ElementRef,
    HostListener,
    inject,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterModule } from '@angular/router';
import {
    ActionDropdownButtonComponent,
    ActionDropdownItem,
    AppSvgIconComponent,
    PaginationControlsComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { catchError, EMPTY, finalize, interval, Observable, Subject, switchMap, takeUntil } from 'rxjs';
import { GraphMessagesComponent } from 'src/app/pages/running-graph/components/graph-messages/graph-messages.component';

import { ExportFormat, ImportExportService } from '../../../../core/services/import-export.service';
import { ToastService } from '../../../../services/notifications/toast.service';
import { downloadBlob } from '../../../../shared/utils/download-blob.util';
import { FlowSessionsTableComponent } from '../../components/flow-sessions-dialog/flow-sessions-table.component';
import { GetGraphLightRequest } from '../../models/graph.model';
import { FlowsApiService } from '../../services/flows-api.service';
import {
    DurationFilter,
    GraphSessionLight,
    GraphSessionService,
    GraphSessionStatus,
} from '../../services/flows-sessions.service';

@Component({
    selector: 'app-global-sessions-list',
    standalone: true,
    imports: [
        CommonModule,
        FlowSessionsTableComponent,
        PaginationControlsComponent,
        AppSvgIconComponent,
        RouterModule,
        GraphMessagesComponent,
        ActionDropdownButtonComponent,
        SelectComponent,
    ],
    templateUrl: './global-sessions-list.component.html',
    styleUrls: ['./global-sessions-list.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GlobalSessionsListComponent {
    @ViewChild('contentRef') contentRef!: ElementRef<HTMLElement>;

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
    public sortOrder = signal<'asc' | 'desc'>('desc');
    public flowFilter = signal<string | null>(null);
    public isErrorCauseFilter = signal<boolean>(false);
    public durationFilter = signal<DurationFilter | null>(null);
    public selectedIds = signal<Set<number>>(new Set());
    public availableFlows = signal<GetGraphLightRequest[]>([]);
    public totalCount = signal(0);
    public isPanelOpen = signal(false);
    public rightPanelWidth = signal(35);
    private isResizing = false;
    private resizeStartX = 0;
    private resizeStartWidth = 0;
    public previewSession = signal<GraphSessionLight | null>(null);
    public isExporting = signal(false);
    public isDeleting = signal(false);
    private reloadTrigger = signal(0);
    private cancelLoad$ = new Subject<void>();
    private cancelPolling$ = new Subject<void>();
    private static readonly POLL_INTERVAL_MS = 5000;
    private destroyRef = inject(DestroyRef);

    readonly exportItems: ActionDropdownItem[] = [
        { label: 'Export as JSON', value: 'json' },
        { label: 'Export as CSV', value: 'csv' },
    ];

    constructor(
        private graphSessionService: GraphSessionService,
        private flowsApiService: FlowsApiService,
        private router: Router,
        private importExportService: ImportExportService,
        private toastService: ToastService
    ) {
        effect(() => {
            const page = this.currentPage();
            const size = this.pageSize();
            const status = this.statusFilter();
            const sort = this.sortOrder();
            const flowName = this.flowFilter();
            const isErrorCause = this.isErrorCauseFilter();
            const durationFilter = this.durationFilter();
            this.reloadTrigger();
            this.loadGlobalSessions(size, (page - 1) * size, status, sort, flowName, isErrorCause, durationFilter);
        });

        this.flowsApiService
            .getGraphsLight()
            .pipe(takeUntilDestroyed())
            .subscribe({
                next: (flows) => {
                    this.availableFlows.set(flows);
                },
            });
    }

    public togglePanel(): void {
        const closing = this.isPanelOpen();
        this.isPanelOpen.update((v) => !v);
        if (closing) {
            this.previewSession.set(null);
        }
    }

    public startResize(event: MouseEvent): void {
        event.preventDefault();
        event.stopPropagation();
        this.isResizing = true;
        this.resizeStartX = event.clientX;
        this.resizeStartWidth = this.rightPanelWidth();
    }

    @HostListener('document:mousemove', ['$event'])
    public onMouseMove(event: MouseEvent): void {
        if (!this.isResizing) return;
        const containerWidth = this.contentRef.nativeElement.getBoundingClientRect().width;
        const dx = this.resizeStartX - event.clientX;
        const dxPercent = (dx / containerWidth) * 100;
        const newWidth = Math.min(60, Math.max(15, this.resizeStartWidth + dxPercent));
        this.rightPanelWidth.set(newWidth);
    }

    @HostListener('document:mouseup')
    public onMouseUp(): void {
        this.isResizing = false;
    }

    public onPageChange(page: number): void {
        this.currentPage.set(page);
    }

    public onPageSizeChange(size: number): void {
        this.pageSize.set(size);
        this.currentPage.set(1);
    }

    public onViewSession(sessionId: number): void {
        const session = this.sessions().find((s) => s.id === sessionId);
        if (session) {
            this.router.navigate(['/graph', session.graph_id, 'session', sessionId]);
        }
    }

    public onIsErrorCauseChange(): void {
        this.isErrorCauseFilter.update((v) => !v);
        this.currentPage.set(1);
    }

    public onFlowFilterChange(name: string | null): void {
        this.flowFilter.set(name);
        this.currentPage.set(1);
    }

    public onBulkDelete(): void {
        this.onDeleteSelected(Array.from(this.selectedIds()));
    }

    public onStatusFilterChange(values: string[]): void {
        this.statusFilter.set(values);
        this.currentPage.set(1);
    }

    public onSortChange(order: 'asc' | 'desc'): void {
        this.sortOrder.set(order);
        this.currentPage.set(1);
    }

    public onPreviewSession(sessionId: number | null): void {
        if (sessionId === null) {
            this.previewSession.set(null);
            this.isPanelOpen.set(false);
            return;
        }
        const session = this.sessions().find((s) => s.id === sessionId) ?? null;
        this.previewSession.set(session);
        if (session) {
            this.isPanelOpen.set(true);
        }
    }

    public onStopSession(sessionId: number): void {
        this.graphSessionService
            .stopSessionById(sessionId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.sessions.update((list) =>
                        list.map((s) =>
                            s.id === sessionId
                                ? { ...s, status: GraphSessionStatus.STOP, finished_at: new Date().toISOString() }
                                : s
                        )
                    );
                },
                error: (err) => {
                    console.error('Failed to stop session', err);
                },
            });
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
                    const previewedSession = this.previewSession();
                    if (previewedSession && ids.includes(previewedSession.id)) {
                        this.previewSession.set(null);
                        this.isPanelOpen.set(false);
                    }

                    const remaining = this.sessions().filter((s) => !ids.includes(s.id));
                    if (remaining.length === 0 && this.currentPage() > 1) {
                        this.currentPage.set(this.currentPage() - 1);
                    } else {
                        this.reloadTrigger.update((val) => val + 1);
                    }
                },
                error: (err) => {
                    console.error('Failed to delete sessions', err);
                },
            });
    }

    public onDurationFilterChange(filter: DurationFilter | null): void {
        this.durationFilter.set(filter);
        this.currentPage.set(1);
    }

    public onExport(format: ExportFormat): void {
        if (this.selectedIds().size === 0 && this.totalCount() === 0) {
            return;
        }
        this.isExporting.set(true);
        let obs$: Observable<Blob>;

        if (this.selectedIds().size > 0) {
            obs$ = this.importExportService.bulkExportSessions(Array.from(this.selectedIds()), format);
        } else {
            const activeStatuses = this.statusFilter().filter((s) => s !== 'all');
            const selectedFlow = this.flowFilter()
                ? this.availableFlows().find((f) => f.name === this.flowFilter())
                : null;
            obs$ = this.importExportService.exportAll(
                {
                    graph: selectedFlow?.id,
                    status: activeStatuses.length > 0 ? activeStatuses : undefined,
                    is_error_cause: this.isErrorCauseFilter() || undefined,
                },
                format
            );
        }

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

    private loadGlobalSessions(
        limit: number,
        offset: number,
        status: string[],
        sort: 'asc' | 'desc' = 'desc',
        graphName?: string | null,
        isErrorCause?: boolean,
        durationFilter?: DurationFilter | null
    ): void {
        this.cancelLoad$.next();
        this.cancelPolling$.next();
        this.isLoaded.set(false);
        const ordering = sort === 'asc' ? 'created_at' : '-created_at';
        this.graphSessionService
            .getGlobalSessions(limit, offset, status, ordering, graphName, isErrorCause, durationFilter)
            .pipe(takeUntil(this.cancelLoad$), takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    this.sessions.set(response.results);
                    this.totalCount.set(response.count);
                    this.isLoaded.set(true);
                    this.startBackgroundRefresh();
                },
                error: () => {
                    this.totalCount.set(0);
                    this.sessions.set([]);
                    this.isLoaded.set(true);
                    this.pageSize.set(10);
                    this.currentPage.set(1);
                },
            });
    }

    private startBackgroundRefresh(): void {
        interval(GlobalSessionsListComponent.POLL_INTERVAL_MS)
            .pipe(
                switchMap(() => {
                    const ordering = this.sortOrder() === 'asc' ? 'created_at' : '-created_at';
                    return this.graphSessionService
                        .getGlobalSessions(
                            this.pageSize(),
                            (this.currentPage() - 1) * this.pageSize(),
                            this.statusFilter(),
                            ordering,
                            this.flowFilter(),
                            this.isErrorCauseFilter(),
                            this.durationFilter()
                        )
                        .pipe(catchError(() => EMPTY));
                }),
                takeUntil(this.cancelPolling$),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((response) => {
                this.sessions.set(response.results);
                this.totalCount.set(response.count);
            });
    }
}
