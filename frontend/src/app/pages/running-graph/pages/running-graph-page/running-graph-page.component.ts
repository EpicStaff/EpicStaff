import { ChangeDetectionStrategy, ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { RouterModule } from '@angular/router';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { GraphDto } from '../../../../features/flows/models/graph.model';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { GraphSessionService, GraphSessionStatus } from '../../../../features/flows/services/flows-sessions.service';
import { ToastService } from '../../../../services/notifications';
import { GraphMessagesComponent } from '../../components/graph-messages/graph-messages.component';
import { RunningGraphHeaderComponent } from '../../components/header/run-graph-header.component';
import { GraphMessage } from '../../models/graph-session-message.model';

@Component({
    selector: 'app-running-graph',
    imports: [RouterModule, RunningGraphHeaderComponent, GraphMessagesComponent],
    templateUrl: './running-graph-page.component.html',
    styleUrls: ['./running-graph-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunningGraphComponent implements OnInit, OnDestroy {
    public graphId: number | null = null;
    public sessionId: string | null = null;
    public graphData: GraphDto | null = null;
    public currentSessionStatus: GraphSessionStatus | null = null;
    public messages: GraphMessage[] = [];

    private destroy$ = new Subject<void>();

    constructor(
        private route: ActivatedRoute,
        private router: Router,
        private toast: ToastService,
        private graphService: FlowsApiService,
        private graphSessionService: GraphSessionService,
        private cdr: ChangeDetectorRef
    ) {}

    public ngOnInit(): void {
        // Extract graphId and sessionId from route parameters
        this.route.paramMap.pipe(takeUntil(this.destroy$)).subscribe((params) => {
            const newGraphId = Number(params.get('graphId'));
            const newSessionId = params.get('sessionId');

            // Only reload graph data if graphId changed
            if (newGraphId !== this.graphId) {
                this.graphId = newGraphId;
                if (isFinite(this.graphId)) {
                    this.loadGraphData(this.graphId);
                }
            } else {
                // Just update the graphId if it's the same
                this.graphId = newGraphId;
            }

            // Update sessionId and trigger change detection
            if (newSessionId !== this.sessionId) {
                this.sessionId = newSessionId;
                this.currentSessionStatus = null; // Reset status for new session
                this.messages = []; // Clear messages for new session
                this.cdr.markForCheck();
            }
        });
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

    private loadGraphData(graphId: number): void {
        this.graphService
            .getGraphById(graphId)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (graph) => {
                    this.graphData = graph;
                    this.cdr.markForCheck();
                },
                error: (err) => {
                    this.toast.error(err.error?.detail || 'Failed to fetch graph');
                    void this.router.navigate(['/sessions']);
                    this.cdr.markForCheck();
                },
            });
    }

    public onStopSession(): void {
        if (!this.sessionId) return;
        this.graphSessionService
            .stopSessionById(Number(this.sessionId))
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: () => {
                    this.currentSessionStatus = GraphSessionStatus.STOP;
                    this.cdr.markForCheck();
                },
                error: (err) => {
                    this.toast.error(err.error?.detail || 'Failed to stop session');
                },
            });
    }

    public handleSessionStatusChange(status: GraphSessionStatus): void {
        this.currentSessionStatus = status;
        this.cdr.markForCheck();
    }

    public handleMessagesChanged(newMessages: GraphMessage[]): void {
        this.messages = newMessages;
        this.cdr.markForCheck();
    }
}
