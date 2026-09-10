import { Dialog } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    EventEmitter,
    HostListener,
    Input,
    OnChanges,
    OnDestroy,
    Output,
    SimpleChanges,
} from '@angular/core';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { Router, RouterModule } from '@angular/router';
import { Subject, takeUntil } from 'rxjs';

import { FlowSessionsListComponent } from '../../../../features/flows/components/flow-sessions-dialog/flow-sessions-list.component';
import {
    getTriggerDisplay,
    TriggerDisplay,
} from '../../../../features/flows/components/flow-sessions-dialog/trigger-display.constants';
import { GraphDto } from '../../../../features/flows/models/graph.model';
import {
    GraphSessionLight,
    GraphSessionService,
    GraphSessionStatus,
    isTerminalSessionStatus,
} from '../../../../features/flows/services/flows-sessions.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { StopSessionButtonComponent } from '../../../../shared/components/buttons/stop-session-button/stop-session-button.component';
import { StatusBadgeComponent } from '../../../../shared/components/status-badge/status-badge.component';
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
        StopSessionButtonComponent,
        SessionIdSwitcherComponent,
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

    constructor(
        private runGraphPageService: RunGraphPageService,
        private memoryService: MemoryService,
        private dialog: Dialog,
        private router: Router,
        private graphSessionService: GraphSessionService
    ) {}

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['graphId'] && this.graphId != null && isFinite(this.graphId)) {
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

    @HostListener('document:keydown.escape')
    handleEscapeKey() {
        this.closeSidebar();
    }

    get memories() {
        return this.runGraphPageService.getMemories();
    }

    get memoriesCount(): number {
        return this.memories.length;
    }

    toggleMemoriesSidebar(): void {
        this.showMemoriesSidebar = !this.showMemoriesSidebar;
    }

    closeSidebar(): void {
        this.showMemoriesSidebar = false;
    }

    onFlowClick() {
        if (this.graphId) {
            this.router.navigate(['flows', this.graphId]);
        }
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
            },
            error: (error) => {
                console.error('Error deleting memory:', error);
                // Could add error handling or notification here
            },
        });
    }
}
