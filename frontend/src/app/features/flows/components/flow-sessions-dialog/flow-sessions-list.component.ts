import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    effect,
    ElementRef,
    Inject,
    OnInit,
    signal,
    ViewChild,
} from '@angular/core';
import { Router } from '@angular/router';
import { IconButtonComponent, PaginationControlsComponent } from '@shared/components';
import { Subject, takeUntil } from 'rxjs';
import { NodeGroup } from 'src/app/shared/models/node-group.model';

import { GraphDto } from '../../models/graph.model';
import { GraphSessionLight, GraphSessionService, GraphSessionStatus } from '../../services/flows-sessions.service';
import { FlowSessionNodeFilterDropdownComponent } from './flow-session-node-filter-dropdown.component';
import { FlowSessionStatusFilterDropdownComponent } from './flow-session-status-filter-dropdown.component';
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
        FlowSessionStatusFilterDropdownComponent,
        FlowSessionNodeFilterDropdownComponent,
        IconButtonComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowSessionsListComponent implements OnInit {
    public flow!: GraphDto;
    public sessions = signal<GraphSessionLight[]>([]);
    public isLoaded = signal<boolean>(false);
    public currentPage = signal(1);
    public pageSize = signal(10);
    public statusFilter = signal<string[]>(['all']);
    public nodeFilter = signal<string | null>(null);
    public totalCount = 0;
    public availableNodes = signal<string[]>([]);
    public isErrorCauseFilter = signal<boolean>(false);
    private reloadTrigger = signal(0);
    public availableNodeGroups = signal<NodeGroup[]>([]);
    public selectedIds = signal<Set<number>>(new Set());
    private cancelLoad$ = new Subject<void>();

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

    public onDeleteSelected(ids: number[]): void {
        if (ids.length === 0) return;

        this.graphSessionService.bulkDeleteSessions(ids).subscribe({
            next: () => {
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
            },
            error: (err) => {
                console.error('Failed to stop session', err);
            },
        });
    }

    onPageChange(page: number) {
        this.currentPage.set(page);
    }

    onStatusFilterChange(values: string[]) {
        this.currentPage.set(1);
        this.statusFilter.set(values);
    }

    public ngOnDestroy() {
        this.cancelLoad$.complete();
        this.sessions.set([]);
    }

    onNodeFilterChange(value: string | null) {
        this.currentPage.set(1);
        this.nodeFilter.set(value);
    }

    public onSelectedIdsChange(ids: Set<number>): void {
        this.selectedIds.set(ids);
    }

    public onBulkDelete(): void {
        this.onDeleteSelected(Array.from(this.selectedIds()));
        this.selectedIds.set(new Set());
    }
}
