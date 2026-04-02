import { CommonModule } from '@angular/common';
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
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';
import { AppIconComponent } from '@shared/components';
import { Subject, takeUntil } from 'rxjs';

import { GraphSessionLight, GraphSessionService } from '../../../../features/flows/services/flows-sessions.service';
import { GraphMessagesComponent } from '../graph-messages/graph-messages.component';

@Component({
    selector: 'app-flow-messages-panel',
    standalone: true,
    imports: [
        CommonModule,
        FormsModule,
        MatSelectModule,
        MatIconModule,
        MatButtonModule,
        MatTooltipModule,
        GraphMessagesComponent,
        AppIconComponent,
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
    public searchQuery = '';
    public isDropdownOpen = false;

    private readonly destroy$ = new Subject<void>();

    constructor(
        private readonly graphSessionService: GraphSessionService,
        private readonly cdr: ChangeDetectorRef,
        private readonly router: Router
    ) {}

    public ngOnInit(): void {
        this.selectedSessionId = this.sessionId;
        this.loadSessions();

        this.graphSessionService.sessionsChanged$.pipe(takeUntil(this.destroy$)).subscribe(() => this.loadSessions());
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['sessionId'] && !changes['sessionId'].firstChange) {
            this.selectedSessionId = this.sessionId;
            this.loadSessions();
        }
        if (changes['graphId'] && !changes['graphId'].firstChange) {
            this.loadSessions();
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

    public onSessionChange(sessionId: string): void {
        this.selectedSessionId = sessionId;
        this.isDropdownOpen = false;
        this.searchQuery = '';
        this.sessionSelected.emit(sessionId);
    }

    public toggleDropdown(): void {
        this.isDropdownOpen = !this.isDropdownOpen;
        if (!this.isDropdownOpen) {
            this.searchQuery = '';
        }
    }

    public closeDropdown(): void {
        this.isDropdownOpen = false;
        this.searchQuery = '';
    }

    public get filteredSessions(): GraphSessionLight[] {
        if (!this.searchQuery) return this.sessions;
        return this.sessions.filter((s) => s.id.toString().includes(this.searchQuery));
    }

    public get selectedSessionLabel(): string {
        const session = this.sessions.find((s) => s.id.toString() === this.selectedSessionId);
        return session ? `ID ${session.id}` : `ID -`;
    }

    public goToPreviousSession(): void {
        const index = this.getCurrentSessionIndex();
        if (index > 0) {
            this.onSessionChange(this.sessions[index - 1].id.toString());
        }
    }

    public goToNextSession(): void {
        const index = this.getCurrentSessionIndex();
        if (index >= 0 && index < this.sessions.length - 1) {
            this.onSessionChange(this.sessions[index + 1].id.toString());
        }
    }

    public get hasPreviousSession(): boolean {
        return this.getCurrentSessionIndex() > 0;
    }

    public get hasNextSession(): boolean {
        const index = this.getCurrentSessionIndex();
        return index >= 0 && index < this.sessions.length - 1;
    }

    public openSessionPage(): void {
        if (this.graphId && this.selectedSessionId) {
            const url = this.router.serializeUrl(
                this.router.createUrlTree(['graph', this.graphId, 'session', this.selectedSessionId])
            );
            window.open(url, '_blank');
        }
    }

    public getTimeAgo(dateStr: string): string {
        const now = Date.now();
        const diff = now - new Date(dateStr).getTime();
        const seconds = Math.floor(diff / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);
        const weeks = Math.floor(days / 7);
        const months = Math.floor(days / 30);

        if (seconds < 60) return 'just now';
        if (minutes < 60) return `${minutes} min ago`;
        if (hours < 24) return `${hours}h ago`;
        if (days < 7) return `${days}d ago`;
        if (weeks < 5) return `${weeks}w ago`;
        return `${months}mo ago`;
    }

    private getCurrentSessionIndex(): number {
        if (!this.selectedSessionId) return -1;
        return this.sessions.findIndex((s) => s.id.toString() === this.selectedSessionId);
    }

    private loadSessions(): void {
        if (!this.graphId) return;

        this.graphSessionService
            .getSessionsByGraphId(this.graphId, false)
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

                    this.cdr.markForCheck();
                },
            });
    }
}
