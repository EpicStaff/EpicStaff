import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    Input,
    OnChanges,
    OnDestroy,
    OnInit,
    Output,
    SimpleChanges,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';
import { Subject, takeUntil } from 'rxjs';

import {
    GraphSessionLight,
    GraphSessionService,
    GraphSessionStatus,
    isTerminalSessionStatus,
} from '../../../../features/flows/services/flows-sessions.service';
import { ToastService } from '../../../../services/notifications';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { StopSessionButtonComponent } from '../../../../shared/components/buttons/stop-session-button/stop-session-button.component';
import { GraphMessagesComponent } from '../graph-messages/graph-messages.component';
import { SessionIdSwitcherComponent } from '../session-id-switcher/session-id-switcher.component';

@Component({
    selector: 'app-flow-messages-panel',
    imports: [
        MatButtonModule,
        MatTooltipModule,
        GraphMessagesComponent,
        AppSvgIconComponent,
        StopSessionButtonComponent,
        SessionIdSwitcherComponent,
    ],
    templateUrl: './flow-messages-panel.component.html',
    styleUrls: ['./flow-messages-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowMessagesPanelComponent implements OnInit, OnChanges, OnDestroy {
    @Input() graphId: number | null = null;
    @Input() sessionId: string | null = null;
    @Output() close = new EventEmitter<void>();
    @Output() sessionSelected = new EventEmitter<string>();

    public sessions: GraphSessionLight[] = [];
    public selectedSessionId: string | null = null;
    public sessionsLoaded = false;

    private readonly destroy$ = new Subject<void>();

    constructor(
        private readonly graphSessionService: GraphSessionService,
        private readonly cdr: ChangeDetectorRef,
        private readonly router: Router,
        private readonly toast: ToastService
    ) {}

    public ngOnInit(): void {
        this.selectedSessionId = this.sessionId;
        this.sessionsLoaded = false;
        this.loadSessions();

        this.graphSessionService.sessionsChanged$.pipe(takeUntil(this.destroy$)).subscribe(() => this.loadSessions());
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['sessionId'] && !changes['sessionId'].firstChange) {
            const newSessionId = changes['sessionId'].currentValue as string | null;
            if (newSessionId !== this.selectedSessionId) {
                this.selectedSessionId = newSessionId;
                this.sessionsLoaded = false;
                this.loadSessions();
            }
        }
        if (changes['graphId'] && !changes['graphId'].firstChange) {
            this.sessionsLoaded = false;
            this.loadSessions();
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

    public onSessionChange(sessionId: string): void {
        this.selectedSessionId = sessionId;
        this.sessionSelected.emit(sessionId);
    }

    public get canStopSelectedSession(): boolean {
        const session = this.sessions.find((s) => s.id.toString() === this.selectedSessionId);
        return !!session && !isTerminalSessionStatus(session.status);
    }

    public onSessionStatusChanged(status: GraphSessionStatus): void {
        if (!this.selectedSessionId) return;
        const sessionId = Number(this.selectedSessionId);
        this.sessions = this.sessions.map((s) => (s.id === sessionId ? { ...s, status } : s));
        this.cdr.markForCheck();
    }

    public onStopSession(): void {
        if (!this.selectedSessionId) return;
        const sessionId = Number(this.selectedSessionId);
        this.graphSessionService
            .stopSessionById(sessionId)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: () => {
                    this.sessions = this.sessions.map((s) =>
                        s.id === sessionId
                            ? { ...s, status: GraphSessionStatus.STOP, finished_at: new Date().toISOString() }
                            : s
                    );
                    this.cdr.markForCheck();
                },
                error: (err) => {
                    this.toast.error(err.error?.detail || 'Failed to stop session');
                },
            });
    }

    public openSessionPage(): void {
        if (this.graphId && this.selectedSessionId) {
            const url = this.router.serializeUrl(
                this.router.createUrlTree(['graph', this.graphId, 'session', this.selectedSessionId])
            );
            window.open(url, '_blank');
        }
    }

    private loadSessions(): void {
        const graphId = this.graphId;
        if (graphId == null || !isFinite(graphId)) return;

        this.graphSessionService
            .getSessionsByGraphId(graphId, false)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (response) => {
                    this.sessions = (response.results as GraphSessionLight[]).sort(
                        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                    );

                    const selectedStillExists =
                        this.selectedSessionId && this.sessions.some((s) => s.id.toString() === this.selectedSessionId);

                    if (!selectedStillExists) {
                        if (this.sessions.length > 0) {
                            this.selectedSessionId = this.sessions[0].id.toString();
                            this.sessionSelected.emit(this.selectedSessionId);
                        } else {
                            this.selectedSessionId = null;
                            this.sessionSelected.emit('');
                        }
                    }

                    this.sessionsLoaded = true;
                    this.cdr.markForCheck();
                },
            });
    }
}
