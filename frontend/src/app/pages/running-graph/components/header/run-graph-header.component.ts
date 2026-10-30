import { Dialog } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    EventEmitter,
    Input,
    OnChanges,
    OnDestroy,
    Output,
    SimpleChanges,
    viewChild,
} from '@angular/core';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltip } from '@angular/material/tooltip';
import { Router, RouterModule } from '@angular/router';
import { AppSvgIconComponent, StatusBadgeComponent } from '@shared/components';
import { DATE_TIME_FORMAT_24H } from '@shared/constants';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, GraphSessionStatus, isTerminalSessionStatus, ResourceCode } from '@shared/models';
import { Subject, takeUntil } from 'rxjs';

import { FlowSessionsListComponent } from '../../../../features/flows/components/flow-sessions-dialog/flow-sessions-list.component';
import {
    getSessionRunType,
    getTriggerDisplay,
    SESSION_RUN_TYPE_LABELS,
    TriggerDisplay,
} from '../../../../features/flows/components/flow-sessions-dialog/trigger-display.constants';
import { GraphDto } from '../../../../features/flows/models/graph.model';
import { GraphSessionLight, GraphSessionService } from '../../../../features/flows/services/flows-sessions.service';
import { StopButtonComponent } from '../../../../shared/components/stop-button/stop-button.component';
import { RunGraphPageService } from '../../services/run-graph-page.service';
import { MemoriesSidebarComponent } from '../memory-sidebar/components/memory-sidebar/memory-sidebar.component';
import { MemoryService } from '../memory-sidebar/service/memory.service';
import { SessionIdSwitcherComponent } from '../session-id-switcher/session-id-switcher.component';
import { SessionFilesButtonComponent } from './session-files-button/session-files-button.component';

@Component({
    selector: 'app-running-graph-header',
    imports: [
        RouterModule,
        MatButtonModule,
        MatBadgeModule,
        DatePipe,
        AppSvgIconComponent,
        StatusBadgeComponent,
        MemoriesSidebarComponent,
        SessionFilesButtonComponent,
        StopButtonComponent,
        SessionIdSwitcherComponent,
        HasPermissionDirective,
        MatTooltip,
    ],
    templateUrl: './run-graph-header.component.html',
    styleUrls: ['./run-graph-header.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
})
export class RunningGraphHeaderComponent implements OnChanges, OnDestroy {
    @Input() graphId: number | null = null;
    @Input() sessionId: string | null | undefined = null;
    @Input() graphName: string | null | undefined = null;
    @Input() sessionStatus: GraphSessionStatus | null = null;
    @Input() graphData: GraphDto | null = null;
    @Output() stopSession = new EventEmitter<void>();

    // The memories sidebar takes the focus when it opens and hands it back to this button when it closes.
    private readonly memoriesButton = viewChild.required('memoriesButton', { read: ElementRef<HTMLButtonElement> });
    private readonly memoriesSidebar = viewChild.required(MemoriesSidebarComponent);

    public readonly DATE_TIME_FORMAT_24H = DATE_TIME_FORMAT_24H;
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    public showMemoriesSidebar = false;
    public sessions: GraphSessionLight[] = [];

    private readonly destroy$ = new Subject<void>();

    get canStop(): boolean {
        return this.sessionStatus !== null && !isTerminalSessionStatus(this.sessionStatus);
    }

    get currentSession(): GraphSessionLight | null {
        return this.sessions.find((s) => s.id.toString() === this.sessionId) ?? null;
    }

    get triggerDisplay(): TriggerDisplay {
        const trigger = this.currentSession?.trigger;
        if (!trigger) return { label: 'Unknown', icon: null, color: null };
        return getTriggerDisplay(trigger.trigger_type);
    }

    /** Empty until the current session is loaded, so the row does not flash "Live" for a test run. */
    get runTypeLabel(): string {
        const session = this.currentSession;
        return session ? SESSION_RUN_TYPE_LABELS[getSessionRunType(session.trigger)] : '';
    }

    constructor(
        private runGraphPageService: RunGraphPageService,
        private memoryService: MemoryService,
        private dialog: Dialog,
        private router: Router,
        private graphSessionService: GraphSessionService
    ) {}

    public ngOnChanges(changes: SimpleChanges): void {
        const graphIdChanged = !!changes['graphId'] && this.graphId != null && isFinite(this.graphId);
        const sessionIdChanged = !!changes['sessionId'] && !changes['sessionId'].firstChange;
        if (graphIdChanged || sessionIdChanged) {
            this.loadSessions();
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

    public onSessionSelected(sessionId: string): void {
        if (!this.graphId || sessionId === this.sessionId) return;
        this.router.navigate(['graph', this.graphId, 'session', sessionId]);
    }

    private loadSessions(): void {
        if (this.graphId == null || !isFinite(this.graphId)) return;
        this.graphSessionService
            .getSessionsByGraphId(this.graphId, false)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (response) => {
                    this.sessions = (response.results as GraphSessionLight[]).sort(
                        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                    );
                },
            });
    }

    get memories() {
        return this.runGraphPageService.getMemories();
    }

    get memoriesCount(): number {
        return this.memories.length;
    }

    toggleMemoriesSidebar(): void {
        if (this.showMemoriesSidebar) {
            this.closeSidebar();
            return;
        }
        this.showMemoriesSidebar = true;
        this.memoriesSidebar().focusWhenOpen();
    }

    closeSidebar(): void {
        if (!this.showMemoriesSidebar) return;
        this.showMemoriesSidebar = false;
        this.memoriesButton().nativeElement.focus();
    }
    openSessionsDialog(): void {
        if (this.graphData) {
            this.dialog.open(FlowSessionsListComponent, {
                data: { flow: this.graphData },
                panelClass: 'custom-dialog-panel',
            });
        }
    }

    handleDeleteMemory(memoryId: string): void {
        this.memoryService.deleteMemory(memoryId).subscribe({
            next: () => {
                // On successful deletion, update local state
                this.runGraphPageService.deleteMemory(memoryId);
                // its delete button went with it
                this.memoriesSidebar().focus();
            },
            error: (error) => {
                console.error('Error deleting memory:', error);
                // Could add error handling or notification here
            },
        });
    }
}
